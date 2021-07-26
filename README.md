# Redmine2Gitea
Converts Redmine issues to Gitea.

It assumes the default labels are enabled for the repository in Gitea, with `support` as an additional label.

## Install
First, rename `sample.env` to `.env` and fill in the necessary values. Then, install the pip dependencies:
```bash
python3 -m pip install -r requirements.txt
```

And simply run the `main.py` script:

```bash
python3 main.py
```
