# Security

paper-repro clones and runs other people's code on your machine. That is the point of the
tool, and it is also the main risk: a repository's training script can do anything your user
account can do. The tool does not sandbox it beyond a separate virtualenv, a timeout and
optional CPU-time limits. Run untrusted repositories in a VM or container you can throw away.

To report a vulnerability in paper-repro itself, open a private security advisory on the
GitHub repository or email the maintainer. Please do not file a public issue first.
