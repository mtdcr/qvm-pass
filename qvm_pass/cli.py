#
# Copyright 2022 Andreas Oberritter
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import base64
import functools
import inspect
import json
import os
import re
import sys
import time
import typing as t
from dataclasses import dataclass, field
from getpass import getpass

import click
import pyperclip
import qrexec.client


@dataclass
class CompletedProcess:
    args: t.List[str]
    returncode: int
    stdout: bytes
    stderr: bytes

    def print_and_quit(self):
        sys.stdout.buffer.write(self.stdout)
        sys.stderr.buffer.write(self.stderr)
        sys.exit(self.returncode)


@dataclass
class QvmPassState:
    qube: str = field(init=False)

    def __post_init__(self):
        app_dir = click.get_app_dir("qvm-pass")
        filename = os.path.join(app_dir, "qube")

        qube = None
        try:
            f = open(filename)
        except FileNotFoundError:
            pass
        except OSError as exc:
            sys.exit(exc)
        else:
            with f:
                lines = f.read().splitlines()
                if lines:
                    qube = lines[0]

        self.qube = qube or "pass-vault"


class PassEntryPoint(click.Group):
    def format_help(self, ctx, formatter):
        p = pass_read(QvmPassState(), "help")
        if p.returncode == 0:
            formatter.write(p.stdout.decode("utf-8"))
        else:
            p.print_and_quit()

    def resolve_command(
        self, ctx: click.Context, args: t.List[str]
    ) -> t.Tuple[t.Optional[str], t.Optional[click.Command], t.List[str]]:
        cmd = self.get_command(ctx, click.utils.make_str(args[0]))
        if cmd is None:
            cmd = self.get_command(ctx, "show")
        else:
            args = args[1:]

        return cmd.name, cmd, args


def pass_entry_point(name: t.Optional[str] = None, **attrs: t.Any) -> t.Callable[[click.decorators.F], PassEntryPoint]:
    attrs.setdefault("cls", PassEntryPoint)
    return t.cast(PassEntryPoint, click.group(name, **attrs))


def pass_rpc(dest: str, rpcname: str, argv: t.List[str], stdin=None) -> CompletedProcess:
    data = {"a": argv}
    if stdin is not None:
        data["i"] = base64.b64encode(stdin.encode("utf-8")).decode("ascii")

    try:
        output = qrexec.client.call(dest, rpcname, arg=argv[0], input=json.dumps(data))
    except Exception as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(output)
    except json.decoder.JSONDecodeError as exc:
        sys.exit(exc)

    p = CompletedProcess(data["a"], data["r"], base64.b64decode(data["o"]), base64.b64decode(data["e"]))
    if p.args[1:] != argv:
        sys.exit("Unexpected reply")

    return p


def pass_read(state: QvmPassState, cmd: str, args: t.Optional[t.List[str]] = []) -> CompletedProcess:
    return pass_rpc(
        state.qube,
        "qubes.PasswordStoreRead",
        [cmd] + args,
    )


def pass_write(state: QvmPassState, cmd: str, args: t.Optional[t.List[str]] = [], stdin=None) -> CompletedProcess:
    return pass_rpc(
        state.qube,
        "qubes.PasswordStoreWrite",
        [cmd] + args,
        stdin=stdin,
    )


def pass_read_generic(state: QvmPassState, cmd: str, *args, **kwargs) -> None:
    if sys.argv[1] != cmd:
        sys.exit(f"Unexpected read command: {sys.argv[1], cmd}")
    p = pass_read(state, cmd, sys.argv[2:])
    p.print_and_quit()


def pass_write_generic(state: QvmPassState, cmd: str, *args, stdin=None, **kwargs) -> None:
    if sys.argv[1] != cmd:
        sys.exit("Unexpected write command")
    p = pass_write(state, cmd, sys.argv[2:], stdin=stdin)
    p.print_and_quit()


def register_command(name: str, callback) -> None:
    context_settings = {"ignore_unknown_options": True}
    params = [click.Argument(("args",), nargs=-1, type=click.UNPROCESSED)]
    cmd = click.Command(
        name,
        context_settings=context_settings,
        callback=functools.partial(click.pass_obj(callback), name),
        params=params,
    )
    qvm_pass.add_command(cmd)


def confirm_overwrite(state: QvmPassState, pass_name: str) -> bool:
    p = pass_read(state, "show", [pass_name])
    if p.returncode != 0:
        return True

    return click.confirm(f"An entry already exists for {pass_name}. Overwrite it?")


def copy_to_clipboard(pass_name: str, password: str) -> None:
    seconds = int(os.getenv("PASSWORD_STORE_CLIP_TIME", "45"))
    kwargs = {}

    copy, paste = pyperclip.determine_clipboard()
    sig = inspect.signature(copy)

    if "primary" in sig.parameters:
        x_selection = os.getenv("PASSWORD_STORE_X_SELECTION", "clipboard")
        for value in ("primary", "secondary", "clipboard"):
            if value.startswith(x_selection):
                x_selection = value
                break
        else:
            sys.exit(f"Invalid value for PASSWORD_STORE_X_SELECTION: {x_selection}")

        kwargs["primary"] = x_selection == "primary"

    old = paste(**kwargs)
    copy(password, **kwargs)

    print(f"Copied {pass_name} to clipboard. Will clear in {seconds} seconds.")

    if os.fork() == 0:
        os.setsid()
        time.sleep(seconds)
        if paste(**kwargs) == password:
            copy(old, **kwargs)


@pass_entry_point(invoke_without_command=True)
@click.pass_context
def qvm_pass(ctx):
    state = QvmPassState()
    ctx.obj = state

    if ctx.invoked_subcommand is None:
        pass_read(state, "ls").print_and_quit()


def show(state: QvmPassState, name: str, **kwargs):
    clip = False
    qrcode = False
    newargs = []
    pass_name = None

    for arg in kwargs["args"]:
        if arg in ("-c", "--clip"):
            clip = True
            line_no = 1
        else:
            for prefix in ("-c", "--clip="):
                if arg.startswith(prefix):
                    clip = True
                    try:
                        line_no = int(arg[len(prefix) :])
                    except ValueError:
                        line_no = 1
                    break
            else:
                if not arg.startswith("-") and pass_name is None:
                    pass_name = arg
                elif arg.startswith("-q") or arg.startswith("--qrcode"):
                    qrcode = True
                newargs.append(arg)

    if clip and not qrcode:
        p = pass_read(state, "show", newargs)
        idx = max(0, line_no - 1)
        lines = p.stdout.decode("utf-8").splitlines()
        if idx >= len(lines):
            print(f"There is no password to put on the clipboard at line {idx}.")
        else:
            copy_to_clipboard(pass_name, lines[idx])
    else:
        if sys.argv[1] == "show":
            pos = 2
        else:
            pos = 1

        pass_read(state, "show", sys.argv[pos:]).print_and_quit()


@qvm_pass.command()
@click.option("-e", "--echo", is_flag=True)
@click.option("-m", "--multiline", is_flag=True)
@click.option("-f", "--force", is_flag=True)
@click.argument("pass-name", required=True)
@click.pass_obj
def insert(state: QvmPassState, pass_name: str, echo: bool, multiline: bool, force: bool) -> None:
    if not force and not confirm_overwrite(state, pass_name):
        sys.exit(1)

    options = "-f"
    if multiline:
        print(f"Enter contents of {pass_name} and press Ctrl+D when finished:\n")
        options += "m"
        passwd = sys.stdin.read()
    elif echo:
        passwd = click.prompt(f"Enter password for {pass_name}") + "\n"
        options += "e"
    else:
        passwd = getpass(f"Enter password for {pass_name}: ") + "\n"
        passwd += getpass(f"Retype password for {pass_name}: ") + "\n"

    pass_write(state, "insert", [options, pass_name], stdin=passwd).print_and_quit()


@qvm_pass.command()
@click.argument("pass-name", required=True)
@click.pass_obj
def edit(state: QvmPassState, pass_name: str) -> None:
    passwd = None

    p = pass_read(state, "show", [pass_name])
    if p.returncode == 0:
        passwd = p.stdout.decode("utf-8")

    new_passwd = click.edit(passwd)
    if new_passwd is None:
        new_passwd = passwd

    pass_write(state, "edit", [pass_name], stdin=new_passwd).print_and_quit()


@qvm_pass.command()
@click.option("-n", "--no-symbols", is_flag=True)
@click.option("-q", "--qrcode", is_flag=True)
@click.option("-c", "--clip", is_flag=True)
@click.option("-i", "--in-place", is_flag=True)
@click.option("-f", "--force", is_flag=True)
@click.argument("pass-name", required=True)
@click.argument("pass-length", required=False, default=25, envvar="PASSWORD_STORE_GENERATED_LENGTH")
@click.pass_obj
def generate(
    state: QvmPassState,
    pass_name: str,
    pass_length: int,
    no_symbols: bool,
    qrcode: bool,
    clip: bool,
    in_place: bool,
    force: bool,
) -> None:
    if not in_place and not force and not confirm_overwrite(state, pass_name):
        sys.exit(1)

    options = "-"
    if no_symbols:
        options += "n"
    if qrcode:
        options += "q"
    if qrcode and clip:
        options += "c"
    if in_place:
        options += "i"
    if force or not in_place:
        options += "f"

    p = pass_write(state, "generate", [options, pass_name, str(pass_length)])
    if p.returncode or not clip:
        p.print_and_quit()

    ansi = re.compile(r"\x1b\[[\d]{1,2}m")
    lines = ansi.sub("", p.stdout.decode("utf-8")).splitlines()
    copy_to_clipboard(pass_name, lines[3])


register_command("show", show)
for cmd in ("ls", "find", "grep", "help", "version"):
    register_command(cmd, pass_read_generic)
for cmd in ("init", "rm", "mv", "cp", "git"):
    register_command(cmd, pass_write_generic)
