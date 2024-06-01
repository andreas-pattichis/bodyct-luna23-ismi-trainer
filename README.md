# LUNA23: Lung Nodule Analysis

![image](https://github.com/andreas-pattichis/bodyct-luna23-ismi-trainer/assets/63289392/93d2ab5f-0b2d-4938-8957-0956d0398a88)

## AIMI2024 Project: LUNA23

### Authors:
- Antonio Carpes, Radboud University
- Andreas Pattichis, Radboud University
- Honor Duthie, Radboud University
- Stanislav Gergert, Radboud University

## Project Overview

This project aimed to improve the LUNA23 baseline results for lung nodule analysis using advanced models. 

## Dataset Description

The dataset originates from the Lung Nodule Analysis 2023 - ISMI educational challenge, evaluating algorithms for lung nodule analysis using chest CT images. It includes:
- Training Set: 687 lung nodule images with pixel-level labels for segmentation and CSV file with labels for nodule type and malignancy.
- Testing Set: 256 lung nodule images without labels, used for final evaluation.

### Key Attributes:
- Volume of interest (VOI): 128 x 128 x 64 voxels.
- Nodule types: non-solid, part-solid, solid, and calcified (classes 0, 1, 2, and 3).
- Malignancy risk: binary labels (0 for non-malignant, 1 for malignant).
- Binary voxel-level labels: class 0 for background, class 1 for nodule. 

## Repository Structure

### 1. Addressing Class Imbalance
- **`train_validation_split.ipynb`**: Jupyter notebook to create balanced training and validation splits using various data augmentation techniques.

### 2. Data Analysis
- **`EDA.ipynb`**: Jupyter notebook for Exploratory Data Analysis (EDA) on the dataset. Provides insights into data distribution, class imbalances, and key statistics.

### 3. Lung Nodule Analysis Inference
- **`inference-baseline-models.py`**: Python script to perform inference using baseline models.
- **`Inference-with-nnUNet.ipynb`**: Jupyter notebook to perform inference using nnU-Net model.

### 4. Training Results Analysis
- **`training-analysis.ipynb`**: Jupyter notebook for analyzing training results, including loss and accuracy plots.
- **`visualization-predictions-heatmaps.ipynb`**: Jupyter notebook for visualizing predictions and generating Grad-CAM heatmaps to understand model focus areas.

### 5. Training Scripts
- **`nnunet_train.sh`**: Shell script to train nnU-Net model.
- **`train_malignancy.py`**: Python script to train model for malignancy classification.
- **`train_noduletype.py`**: Python script to train model for nodule type classification.
- **`train_segmentation.py`**: Python script to train model for segmentation.
- **`VIT_train.py`**: Python script to train Vision Transformer model for nodule type classification.

### 6. Other Scripts and Files
- **`dataloader.py`**: Python script for data loading and preprocessing.
- **`inference.py`**: Python script for performing inference on test set.
- **`networks.py`**: Python script defining network architectures.
- **`README.md`**: This readme file.
- **`requirements.txt`**: File containing the list of dependencies required to run the code.
- 

For more detailed explanations of the study and results, please refer to the project report.
