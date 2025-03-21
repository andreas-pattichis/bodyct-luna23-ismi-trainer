import pandas
import dataloader
import torch
import torch.nn.functional as F
from pathlib import Path
from tqdm import tqdm
import networks
import numpy as np
from datetime import datetime
from sklearn.model_selection import StratifiedKFold
import sklearn.metrics as skl_metrics
from typing import List


logging = dataloader.logging


def dice_loss(input, target):
    """Function to compute dice loss
    source: https://github.com/pytorch/pytorch/issues/1249#issuecomment-305088398

    Args:
        input (torch.Tensor): predictions
        target (torch.Tensor): ground truth mask

    Returns:
        dice loss: 1 - dice coefficient
    """
    smooth = 1.0

    iflat = input.view(-1)
    tflat = target.view(-1)
    intersection = (iflat * tflat).sum()

    return 1 - ((2.0 * intersection + smooth) / (iflat.sum() + tflat.sum() + smooth))


def make_development_splits(
    train_set: pandas.DataFrame,
    save_path: Path,
    n_folds: int = 5,
):
    """Function to split your training set into 5 folds at a patient-level

    Args:
        train_set (pandas.DataFrame): pandas dataframe that contains list of nodules
        save_path (Path): path to save the splits
        n_folds (int, optional): number of folds. Defaults to 5.
    """

    np.random.seed(2023)

    save_path = Path(save_path)
    save_path.mkdir(exist_ok=True, parents=True)

    pids = train_set.patientid.unique()
    labs = [train_set[train_set.patientid == pid].malignancy.values[0] for pid in pids]
    labs = np.array(labs)

    assert len(pids) == len(labs)

    skf = StratifiedKFold(n_splits=n_folds)
    skf.get_n_splits(pids, labs)

    folds_missing = False

    for idx in range(n_folds):

        train_pd = save_path / f"train{idx}.csv"
        valid_pd = save_path / f"valid{idx}.csv"

        if not train_pd.is_file():
            folds_missing = True

        if not valid_pd.is_file():
            folds_missing = True

    if folds_missing:

        print(f"Making {n_folds} folds from the train set")

        for idx, (train_index, test_index) in enumerate(skf.split(pids, labs)):

            train_pids, valid_pids = pids[train_index], pids[test_index]

            train_pd = train_set[train_set.patientid.isin(train_pids)]
            valid_pd = train_set[train_set.patientid.isin(valid_pids)]

            train_pd = train_pd.reset_index(drop=True)
            valid_pd = valid_pd.reset_index(drop=True)

            train_pd.to_csv(save_path / f"train{idx}.csv", index=False)
            valid_pd.to_csv(save_path / f"valid{idx}.csv", index=False)


class NoduleAnalyzer:
    """Class to train a multi-task nodule analyzer"""

    def __init__(
        self,
        best_metric_fn,
        workspace: Path,
        experiment_id: int,
        fold: int = 0,
        batch_size: int = 4,
        num_workers: int = 16,
        max_epochs: int = 1000,
        tasks: List = [
            "segmentation",
            "malignancy",
            "noduletype",
        ],
    ) -> None:

        self.workspace = workspace
        self.batch_size = batch_size
        self.num_workers = num_workers

        self.size_mm = 50
        self.size_px = 64
        self.patch_size = np.array([64, 128, 128])
        self.max_rotation_degree = 20

        self.max_epochs = max_epochs
        self.learning_rate = 1e-4

        self.best_metric_fn = best_metric_fn

        date = datetime.today().strftime("%Y%m%d")
        self.exp_id = f"{date}_{experiment_id}"

        self.fold = fold
        self.tasks = tasks

        train_df_path = workspace / "data" / "luna23-ismi-train-set.csv"
        make_development_splits(
            train_set=pandas.read_csv(train_df_path),
            save_path=workspace / "data" / "train_set" / "folds",
        )

        self.train_df = pandas.read_csv(
            workspace / "data" / "train_set" / "folds" / f"train{fold}.csv"
        )
        self.valid_df = pandas.read_csv(
            workspace / "data" / "train_set" / "folds" / f"valid{fold}.csv"
        )

    def _initialize_model(self, model):

        torch.backends.cudnn.benchmark = True
        # https://stackoverflow.com/questions/58961768/set-torch-backends-cudnn-benchmark-true-or-not

        # define the GPU - ideally this is the first GPU, hence cuda:0
        self.device = torch.device("cuda:0")

        # transfer model to GPU
        self.model = model.to(self.device)

        # define the optimzer
        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.learning_rate,
        )

    def _initialize_data_loaders(self):

        if "malignancy" in self.tasks:
            x = self.train_df.malignancy.values
            x = dataloader.make_weights_for_balanced_classes(x)
            weights = x

        if "noduletype" in self.tasks:
            y = self.train_df.noduletype.values
            y = [dataloader.NODULETYPE_MAPPING[t] for t in y]
            y = dataloader.make_weights_for_balanced_classes(y)
            weights = y

        if "malignancy" in self.tasks and "noduletype" in self.tasks:
            weights = x * y  # 🥚 Easter egg

        if "malignancy" in self.tasks or "noduletype" in self.tasks:
            weights = torch.DoubleTensor(weights)
            sampler = torch.utils.data.sampler.WeightedRandomSampler(
                weights,
                len(self.train_df),
            )

        if self.tasks == ["segmentation"]:
            sampler = None

        self.train_loader = dataloader.get_data_loader(
            self.workspace / "data" / "train_set",
            self.train_df,
            sampler=sampler,
            workers=self.num_workers // 2,
            batch_size=self.batch_size,
            rotations=[(-self.max_rotation_degree, self.max_rotation_degree)] * 3,
            translations=True,
            size_mm=self.size_mm,
            size_px=self.size_px,
            patch_size=self.patch_size,
        )

        self.valid_loader = dataloader.get_data_loader(
            self.workspace / "data" / "train_set",
            self.valid_df,
            workers=self.num_workers // 2,
            batch_size=self.batch_size,
            size_mm=self.size_mm,
            size_px=self.size_px,
            patch_size=self.patch_size,
        )

    def forward(self, batch_data, update_weights=False):

        images, masks, noduletype_targets, malignancy_targets = (
            batch_data["image"].to(self.device),
            batch_data["mask"].to(self.device),
            batch_data["noduletype_target"].to(self.device),
            batch_data["malignancy_target"].to(self.device),
        )

        targets, losses = {}, {}
        loss = 0  # 🥚 Easter egg

        if update_weights:
            self.optimizer.zero_grad()

        outputs = self.model(images)  # do the forward pass

        if "malignancy" in self.tasks:

            malignancy_loss = F.binary_cross_entropy(
                outputs["malignancy"],
                malignancy_targets,
            )

            losses["malignancy"] = malignancy_loss.item()
            outputs["malignancy"] = outputs["malignancy"].data.cpu().numpy().reshape(-1)
            targets["malignancy"] = malignancy_targets.data.cpu().numpy().reshape(-1)

            loss += malignancy_loss

        if "noduletype" in self.tasks:

            noduletype_loss = F.cross_entropy(
                outputs["noduletype"],
                noduletype_targets.squeeze().long(),
            )

            losses["noduletype"] = noduletype_loss.item()
            outputs["noduletype"] = (
                outputs["noduletype"].data.cpu().numpy().reshape(-1, 4)
            )
            targets["noduletype"] = noduletype_targets.data.cpu().numpy().reshape(-1)

            loss += noduletype_loss

        if "segmentation" in self.tasks:

            segmentation_loss = dice_loss(
                outputs["segmentation"],
                masks,
            )

            losses["segmentation"] = segmentation_loss.item()
            outputs["segmentation"] = outputs["segmentation"]
            targets["segmentation"] = masks.data.cpu().numpy()

            loss += segmentation_loss

        losses["total"] = loss.item()

        if update_weights:
            loss.backward()
            self.optimizer.step()

        return outputs, targets, losses

    def train(self, model):

        self._initialize_data_loaders()
        self._initialize_model(model)

        save_dir = self.workspace / "results" / self.exp_id / f"fold{self.fold}"
        save_dir.mkdir(exist_ok=True, parents=True)

        epoch_metrics = {
            "training": [],
            "validation": [],
        }

        best_metric = 0
        best_epoch = 0

        for epoch in range(self.max_epochs):

            for mode in ["training", "validation"]:

                print("\n\n")
                logging.info(
                    f" {mode}, epoch: {epoch + 1} / {self.max_epochs}, with fold: {self.fold}"
                )
                logging.info(f"Tasks being trained: {self.tasks}")

                if mode == "training":
                    self.model.train()
                    data = self.train_loader
                else:
                    self.model.eval()
                    data = self.valid_loader

                metrics = {
                    task: {
                        "loss": [],
                    }
                    for task in self.tasks
                }
                metrics["cumulative"] = {"loss": []}

                predictions = {task: [] for task in self.tasks}
                labels = {task: [] for task in self.tasks}

                for batch_data in tqdm(data):

                    if mode == "training":

                        outputs, targets, losses = self.forward(
                            batch_data,
                            update_weights=True,
                        )

                    else:

                        with torch.no_grad():
                            outputs, targets, losses = self.forward(
                                batch_data,
                                update_weights=False,
                            )

                    for task in self.tasks:
                        metrics[task]["loss"].append(losses[task])

                    metrics["cumulative"]["loss"].append(losses["total"])

                    for task in self.tasks:
                        predictions[task].extend(outputs[task])
                        labels[task].extend(targets[task])

                for task in self.tasks:
                    loss = np.mean(metrics[task]["loss"])
                    metrics[task]["loss"] = loss  # aggregate the loss

                metrics["cumulative"]["loss"] = np.mean(metrics["cumulative"]["loss"])

                if "malignancy" in self.tasks:

                    x = predictions["malignancy"]
                    y = labels["malignancy"]
                    metrics["malignancy"]["auc"] = skl_metrics.roc_auc_score(y, x)

                if "noduletype" in self.tasks:

                    x = [p.argmax() for p in predictions["noduletype"]]
                    y = labels["noduletype"]

                    metrics["noduletype"][
                        "balanced_accuracy"
                    ] = skl_metrics.balanced_accuracy_score(y, x)

                if "segmentation" in self.tasks:

                    dice = 1 - np.mean(metrics["segmentation"]["loss"])
                    metrics["segmentation"]["dice"] = dice

                epoch_metrics[mode].append(metrics)

                if mode == "validation":

                    if self.best_metric_fn(metrics) > best_metric:

                        print("\n===== Saving best model! =====\n")
                        best_metric = self.best_metric_fn(metrics)
                        best_epoch = epoch
                        torch.save(
                            self.model.state_dict(),
                            save_dir / "best_model.pth",
                        )
                        np.save(save_dir / "best_metrics.npy", metrics)

                    else:

                        print(f"Model has not improved since epoch {best_epoch + 1}")

                metrics = pandas.DataFrame(metrics).round(3)
                metrics.replace(np.nan, "", inplace=True)
                print(metrics.to_markdown(tablefmt="grid"))

            np.save(save_dir / "metrics.npy", epoch_metrics)


if __name__ == "__main__":

    #path to the Snellius temporal directory where dataset and results are stored
    workspace = Path("/gpfs/scratch1/nodespecific/int5/calberto/")

    #best_metric_fn return metrics for noduletype which is balanced accuracy
    def best_metric_fn(metrics):
        return metrics["noduletype"][
                        "balanced_accuracy"
                    ]  # 🥚 Easter egg

    ## uncomment the following block for the classification tasks
    model = networks.CNN3D(
         n_input_channels=1,
         n_output_channels=4,  # set output channels to 4 for noduletype classification
         task="noduletype"
    )

    nodule_analyzer = NoduleAnalyzer(
        workspace=workspace,
        best_metric_fn=best_metric_fn,
        experiment_id="0_noduletype",  # give your experiment a unique ID, for each run
        batch_size=32,  # increase batch size to 32 
        fold=0,  # 🥚 Easter egg
        max_epochs=1000,  # set max epochs to 1000
        tasks=["noduletype"],  # 🥚 Easter egg
    )
    nodule_analyzer.train(model)  # 🥚 Easter egg

