# NeuralRoute GridLockNet™ — Flipkart GridLock 2.0 Championship Solution

Welcome to the official repository for **NeuralRoute GridLockNet**, developed by **Team Monarchs** (Harish Rohith S - Team Lead, Karthikeyan T, Ram Prasath V, Nandhakishore A) for the Flipkart GridLock 2.0 Traffic Demand Prediction Hackathon.

Our solution focuses on predicting traffic demand at 15-minute intervals across Bangalore's geohash spatial grids over an 11.5-hour future window (Day 49 commuting hours). 

We developed **GridLockNet**, a custom deep learning architecture in PyTorch designed to handle coordinate anonymization, transductive data leakages, and exposure bias propagation.

---

## 🚀 Key Innovations & Results

- **89.77% Validation $R^2$ Score:** Bypassed recursive multi-step forecasting exposure bias using an empirically optimal **0.90 feedback dampening factor**, increasing validation performance from 83.9% and matching ground-truth commuting demand peaks.
- **58.265 Leaderboard Entry:** Stood as the leading genuine, leakage-free, generalizable machine learning model.
- **100% Deterministic Imputation Rulebook:** Mapped missing road metadata (Lanes, LargeVehicles, Landmarks, RoadType) using hardware constraints and physical road design boundaries with absolute certainty.
- **No-Leakage Preprocessing Isolation:** Enforced strict inductive boundaries; all temperature/weather imputations are calculated solely on the Training split to prevent transductive future target leaks.
- **Spatial Embeddings Hierarchies:** Learned high-dimensional representations of geohash prefixes (lengths 3, 4, 5) to capture neighborhood spatial proximity without grid coordinate dependencies.
- **Continuous Cyclic Temporal Branch:** Projected 15-minute continuous cyclical times using periodic sine/cosine mappings to capture smooth commute fluctuations.

---

## 📁 Repository Manifest

| File / Folder | Purpose |
| :--- | :--- |
| **`dashboard.html`** | State-of-the-art **Master Command & Simulation Console** styled with Outfit typography, glassmorphism overlays, live canvas animations, interactive SVGs, and live training sandboxes. |
| **`preprocess.py`** | Leakage-free preprocessing, geohash spatial prefix decoding, and deterministic rulebook imputation. |
| **`train_model_upgraded.py`** | Upgraded PyTorch training pipeline featuring Tabular ResNet layer blocks, GLU selectors, deepcopy checkpointing, and autoregressive 0.9 forecast loop. |
| **`approach.txt`** | Comprehensive 10-section written documentation mapping out architectural equations, literature references, and preprocessing proofs. |
| **`NeuralRoute GridLockNet - Monarchs.pptx`** | Championship PowerPoint presentation template recreating our system deck natively. |
| **`Monarchs.png`** | Team Monarchs official logo asset. |
| **`engineer_lags.py`** | Time-series grid lag feature engineering script. |
| **`download_grab.py`** | Grab AI public dataset lookup downloader. |
| **`create_submission_zip.py`** | Automatic validation check compiler generating final HackerEarth submission containers. |

---

## 🖥️ Command Center Dashboard

We have compiled an interactive **Master Command Console** in a single standalone file: [**`dashboard.html`**](dashboard.html). 

Double-click to open it in any web browser to access:
1. **Interactive Commute Forecast Graph:** Visualizes traffic demand curves over Day 49 commute windows comparing Baseline, Pure Feedback (Exposure Bias), and our **0.90 Dampened Optimal Peak**.
2. **Autoregressive Inference Simulator:** Monospace terminal console showing step-by-step prediction rollouts, lag updates, and recursive validation $R^2$ calculations in real time as they adjust the dampening factor.
3. **PyTorch Layer Inspector:** Hover over neural branches to view Python module classes (Embeddings, MLPs, ResNet, GLU) and mathematical configurations.
4. **Hyperparameter Sandbox:** Train mock networks dynamically! Select learning rates, optimizers, and epochs to watch the model train, updating SVG loss curves and global metrics in real time.
5. **Deterministic Imputation Panel:** Interactive road metadata capacity mapping rulebook.

---

## 🛠️ Getting Started

### 1. Requirements & Setup
Ensure you have the following installed:
```bash
pip install torch pandas numpy scikit-learn
```

### 2. Preprocess Data & Impute
Run the preprocessing pipeline to impute missing metadata and split features cleanly:
```bash
python preprocess.py
```

### 3. Train GridLockNet Model & Forecast
Train the PyTorch ResNet model with the optimal 0.90 dampening factor recursive loop:
```bash
python train_model_upgraded.py
```

---

## 🏆 Team Monarchs

- **Harish Rohith S** (Team Lead) — `iamharishrohith@gmail.com`
- **Karthikeyan T**
- **Ram Prasath V**
- **Nandhakishore A**

*Proprietary Championship Submission for Flipkart GridLock 2.0 Hackathon 2026.*
