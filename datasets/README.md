# ML Dataset Builder

## Purpose
Generate file-level training data for the Risk Assessment model using
Git history and lightweight source-code metrics.

## Training repositories
| Repository | Files | Risky labels |
|---|---:|---:|
| commons-lang | 464 | 93 |
| commons-io | 501 | 88 |
| jsoup | 137 | 39 |
| gson | 212 | 54 |
| commons-collections | 597 | 58 |
| commons-codec | 154 | 32 |
| commons-compress | 586 | 47 |
| commons-text | 201 | 17 |
| Total | 2852 | 428 |

## Configuration
- History cutoff: 0.7 (70% of commit history).
- Source extension: .java (default).
- Future labeling window: unrestricted after the cutoff because
  --window-days was not specified.
- Maximum files in a qualifying bug-fix commit: 10.
- Bug-fix detection: commit-message regular expressions, with
  exclusions for documentation, style, build and other housekeeping changes.

## Features
Git-history features include change count, authors, lines added and deleted,
churn, file age, time since last change, past bug-fix count, and average
files per commit.

Source-level features include lines of code (loc), branch count, and method
count. These are lightweight regex-based approximations.

## Label definition and limitations
label_future_bugfix is 1 when a file is touched by at least one qualifying
bug-fix commit after the cutoff; otherwise it is 0.

These are proxy labels inferred from commit messages, not independently
verified defects. Regex-based source metrics are approximations and may
not accurately measure all Java constructs.

Features are calculated from the cutoff version and its preceding history.
The future history is used for labels.

## Generated files
One CSV per repository is stored in this directory. Each dataset includes
the repository and file identifiers, 12 numeric features, and the target
label. The eight datasets contain 2,852 records and 428 positive labels.

No model training is performed in this step.
