#!/bin/sh
  
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=18
#SBATCH --gpus=1
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --gpus-per-node=1

module load 2023
module load Python/3.11.3-GCCore-12.3.0

pip3 install --upgrade pip
pip3 install nnunetv2
pip3 install lxml
pip3 install rtree

export nnUNet_raw="/gpfs/scratch1/nodespecific/int5/calberto/data_nn/nnUNet_raw"
export nnUNet_results="/gpfs/scratch1/nodespecific/int5/calberto/data_nn/nnUNet_results"
export nnUNet_preprocessed="/gpfs/scratch1/nodespecific/int5/calberto/data_nn/nnUNet_preprocessed"

echo "Preprocessing"

nnUNetv2_plan_and_preprocess -d 1 --verify_dataset_integrity -pl nnUNetPlannerResEncM

echo "Done preprocessing"

echo "Training"
nnUNetv2_train Dataset001_LUNA 3d_fullres all --npz -p nnUNetResEncUNetMPlans -device cuda

mkdir $HOME/nnunet_results
cp -r $nnUNet_results $HOME/nnunet_results
