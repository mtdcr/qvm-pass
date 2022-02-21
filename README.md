# qvm-pass

*qvm-pass* is a frontend for [pass](https://www.passwordstore.org/) running in a vault VM, in other words it is an implementation of *split-pass* in the spirit of [split-gpg](https://github.com/mtdcr/qubes-app-split-gpg) and [split-ssh](https://github.com/mtdcr/qubes-app-split-ssh). It uses the RPC interface of [Qubes](https://www.qubes-os.org/) called [qrexec](https://www.qubes-os.org/doc/qrexec/), which behaves roughly like a serial connection. Where the RPC interface limits interactivity, *qvm-pass* aims to mimic the same user interface as known from the original `pass` command. However, the `git` subcommand gets blocked, because it would allow the execution of dangerous operations.

**This code was written in a very short time frame and hasn't had any peer review or testing. Use at your own risk!**

## Installation

### Location: AppVM for qvm-pass

#### 1. Clone the repository

`git clone https://github.com/mtdcr/qvm-pass`

#### 2. Install pass script to ~/.local/bin

`pipx install ./qvm-pass`

#### 3. Copy qrexec service to TemplateVM for pass-vault

`qvm-copy qvm-pass/qubes-rpc/qubes.PasswordStoreWrite`

### Location: Dom0

#### 4. Install qrexec policies

Create policy files:

- `/etc/qubes-rpc/policy/qubes.PasswordStoreRead`
- `/etc/qubes-rpc/policy/qubes.PasswordStoreWrite`

Examples can be found in [`qubes-rpc/policy`](https://github.com/mtdcr/qvm-pass/tree/master/qubes-rpc/policy).

### Location: TemplateVM for pass-vault

#### 5. Install qrexec service for write operations

`sudo install -m755 ~/QubesIncoming/*/qubes.PasswordStoreWrite /etc/qubes-rpc/`

#### 6. Create symlink for qrexec service for read operations

`sudo ln -s qubes.PasswordStoreWrite /etc/qubes-rpc/qubes.PasswordStoreRead`

## Configuration

*qvm-pass* reads the name of the vault VM from `~/.config/qvm-pass/qube`. It defaults to `pass-vault`.

### Supported environment variables and their default values

- `PASSWORD_STORE_CLIP_TIME=45`
- `PASSWORD_STORE_GENERATED_LENGTH=25`
- `PASSWORD_STORE_X_SELECTION=clipboard`

## Alternatives

- [qubes-pass](https://github.com/Rudd-O/qubes-pass) - It uses a slightly modified command-line interface compared to the original `pass` command.
