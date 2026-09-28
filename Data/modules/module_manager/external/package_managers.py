"""Host package-manager adapters for dependency installation.

Adapters only — InstallationService remains the install execution authority.
All commands use argv lists (shell=False). Package names must originate from
the trusted dependency registry, never from third-party manifests.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from .dependencies import (
    CommandRunner,
    PrivilegeState,
    SubprocessCommandRunner,
)


class PackageManagerId(str, Enum):
    APT = "apt"
    DNF = "dnf"
    YUM = "yum"
    PACMAN = "pacman"
    ZYPPER = "zypper"
    APK = "apk"
    BREW = "brew"
    WINGET = "winget"
    CHOCO = "choco"


@dataclass(frozen=True)
class HostPlatformInfo:
    system: str
    machine: str
    distro_id: str | None
    distro_like: str | None
    os_release: dict[str, str]

    def public_dict(self) -> dict[str, str | None]:
        return {
            "system": self.system,
            "machine": self.machine,
            "distro_id": self.distro_id,
            "distro_like": self.distro_like,
        }


class HostPackageManager(Protocol):
    manager_id: str

    def available(self) -> bool: ...

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]: ...

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]: ...

    def build_refresh_argv(self) -> list[list[str]]: ...

    def supports_user_scope(self) -> bool: ...


def _which(name: str) -> str | None:
    return shutil.which(name)


def read_os_release(path: str | Path = "/etc/os-release") -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def detect_platform(*, os_release: Mapping[str, str] | None = None) -> HostPlatformInfo:
    release = dict(os_release) if os_release is not None else (
        read_os_release() if platform.system().lower() == "linux" else {}
    )
    return HostPlatformInfo(
        system=platform.system(),
        machine=platform.machine(),
        distro_id=release.get("ID"),
        distro_like=release.get("ID_LIKE"),
        os_release=release,
    )


class AptManager:
    manager_id = PackageManagerId.APT.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("apt-get") or _which("apt"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        dpkg = _which("dpkg-query")
        for pkg in packages:
            if not dpkg:
                out[pkg] = False
                continue
            completed = self._runner.run(
                [dpkg, "-W", "-f=${Status}", pkg],
                timeout=30.0,
            )
            status = (completed.stdout or "").strip().lower()
            out[pkg] = completed.returncode == 0 and "install ok installed" in status
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        apt_get = _which("apt-get") or "apt-get"
        return [[apt_get, "update", "-y"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        apt_get = _which("apt-get") or "apt-get"
        return [[apt_get, "install", "-y", "--no-install-recommends", *packages]]


class DnfManager:
    manager_id = PackageManagerId.DNF.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("dnf"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        dnf = _which("dnf") or "dnf"
        for pkg in packages:
            completed = self._runner.run([dnf, "list", "installed", pkg], timeout=60.0)
            out[pkg] = completed.returncode == 0
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        dnf = _which("dnf") or "dnf"
        return [[dnf, "makecache", "-y"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        dnf = _which("dnf") or "dnf"
        return [[dnf, "install", "-y", *packages]]


class YumManager:
    manager_id = PackageManagerId.YUM.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("yum")) and not bool(_which("dnf"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        yum = _which("yum") or "yum"
        for pkg in packages:
            completed = self._runner.run([yum, "list", "installed", pkg], timeout=60.0)
            out[pkg] = completed.returncode == 0
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        yum = _which("yum") or "yum"
        return [[yum, "makecache", "-y"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        yum = _which("yum") or "yum"
        return [[yum, "install", "-y", *packages]]


class PacmanManager:
    manager_id = PackageManagerId.PACMAN.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("pacman"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        pacman = _which("pacman") or "pacman"
        for pkg in packages:
            completed = self._runner.run([pacman, "-Q", pkg], timeout=30.0)
            out[pkg] = completed.returncode == 0
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        pacman = _which("pacman") or "pacman"
        return [[pacman, "-Sy", "--noconfirm"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        pacman = _which("pacman") or "pacman"
        return [[pacman, "-S", "--noconfirm", "--needed", *packages]]


class ZypperManager:
    manager_id = PackageManagerId.ZYPPER.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("zypper"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        zypper = _which("zypper") or "zypper"
        for pkg in packages:
            completed = self._runner.run([zypper, "search", "-i", "-x", pkg], timeout=60.0)
            out[pkg] = completed.returncode == 0 and pkg in (completed.stdout or "")
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        zypper = _which("zypper") or "zypper"
        return [[zypper, "refresh"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        zypper = _which("zypper") or "zypper"
        return [[zypper, "install", "-y", *packages]]


class ApkManager:
    manager_id = PackageManagerId.APK.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("apk"))

    def supports_user_scope(self) -> bool:
        return False

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        apk = _which("apk") or "apk"
        for pkg in packages:
            completed = self._runner.run([apk, "info", "-e", pkg], timeout=30.0)
            out[pkg] = completed.returncode == 0
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        apk = _which("apk") or "apk"
        return [[apk, "update"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        apk = _which("apk") or "apk"
        return [[apk, "add", *packages]]


class BrewManager:
    manager_id = PackageManagerId.BREW.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return bool(_which("brew"))

    def supports_user_scope(self) -> bool:
        return True

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        brew = _which("brew") or "brew"
        for pkg in packages:
            completed = self._runner.run([brew, "list", "--versions", pkg], timeout=60.0)
            out[pkg] = completed.returncode == 0 and bool((completed.stdout or "").strip())
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        brew = _which("brew") or "brew"
        return [[brew, "update"]]

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        brew = _which("brew") or "brew"
        return [[brew, "install", *packages]]


class WingetManager:
    manager_id = PackageManagerId.WINGET.value

    def __init__(self, runner: CommandRunner | None = None) -> None:
        self._runner = runner or SubprocessCommandRunner()

    def available(self) -> bool:
        return platform.system().lower() == "windows" and bool(_which("winget"))

    def supports_user_scope(self) -> bool:
        return True

    def query_installed(self, packages: Sequence[str]) -> dict[str, bool]:
        out: dict[str, bool] = {}
        winget = _which("winget") or "winget"
        for pkg in packages:
            completed = self._runner.run(
                [winget, "list", "--id", pkg, "--exact"],
                timeout=90.0,
            )
            text = ((completed.stdout or "") + (completed.stderr or "")).lower()
            out[pkg] = completed.returncode == 0 and pkg.lower() in text
        return out

    def build_refresh_argv(self) -> list[list[str]]:
        return []

    def build_install_argv(self, packages: Sequence[str]) -> list[list[str]]:
        if not packages:
            return []
        winget = _which("winget") or "winget"
        return [
            [
                winget,
                "install",
                "--id",
                pkg,
                "--exact",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ]
            for pkg in packages
        ]


def _linux_manager_preference(info: HostPlatformInfo) -> list[str]:
    distro = (info.distro_id or "").lower()
    like = (info.distro_like or "").lower()
    tokens = f"{distro} {like}"
    if any(t in tokens for t in ("debian", "ubuntu", "raspbian", "linuxmint", "pop")):
        return ["apt", "dnf", "yum", "pacman", "zypper", "apk"]
    if any(t in tokens for t in ("fedora", "rhel", "centos", "rocky", "almalinux")):
        return ["dnf", "yum", "apt", "pacman", "zypper", "apk"]
    if any(t in tokens for t in ("arch", "manjaro", "endeavouros")):
        return ["pacman", "apt", "dnf", "yum", "zypper", "apk"]
    if any(t in tokens for t in ("opensuse", "sles", "suse")):
        return ["zypper", "dnf", "yum", "apt", "pacman", "apk"]
    if "alpine" in tokens:
        return ["apk", "apt", "dnf", "yum", "pacman", "zypper"]
    return ["apt", "dnf", "yum", "pacman", "zypper", "apk"]


def build_manager_map(runner: CommandRunner | None = None) -> dict[str, HostPackageManager]:
    r = runner or SubprocessCommandRunner()
    return {
        "apt": AptManager(r),
        "dnf": DnfManager(r),
        "yum": YumManager(r),
        "pacman": PacmanManager(r),
        "zypper": ZypperManager(r),
        "apk": ApkManager(r),
        "brew": BrewManager(r),
        "winget": WingetManager(r),
    }


def detect_package_manager(
    *,
    platform_info: HostPlatformInfo | None = None,
    runner: CommandRunner | None = None,
    managers: Mapping[str, HostPackageManager] | None = None,
) -> HostPackageManager | None:
    """Deterministic selection of one supported package manager."""
    info = platform_info or detect_platform()
    mgrs = dict(managers) if managers is not None else build_manager_map(runner)
    system = info.system.lower()

    if system == "darwin":
        order = ["brew"]
    elif system == "windows":
        order = ["winget"]
    else:
        order = _linux_manager_preference(info)

    for mid in order:
        mgr = mgrs.get(mid)
        if mgr is not None and mgr.available():
            return mgr
    # Fallbacks: any available known manager in stable order.
    for mid in ("apt", "dnf", "yum", "pacman", "zypper", "apk", "brew", "winget"):
        if mid in order:
            continue
        mgr = mgrs.get(mid)
        if mgr is not None and mgr.available():
            return mgr
    return None


def discover_privilege_state(
    *,
    manager: HostPackageManager | None,
    euid: int | None = None,
    sudo_noninteractive: bool | None = None,
    runner: CommandRunner | None = None,
) -> PrivilegeState:
    """Determine whether system package installation can proceed without a TTY password."""
    if manager is None:
        return PrivilegeState.UNSUPPORTED

    if manager.supports_user_scope():
        return PrivilegeState.USER_SCOPE_INSTALL_AVAILABLE

    if euid is None:
        try:
            euid = os.geteuid()  # type: ignore[attr-defined]
        except AttributeError:
            euid = 0 if os.name == "nt" else 1

    if euid == 0:
        return PrivilegeState.ALREADY_PRIVILEGED

    if sudo_noninteractive is None:
        sudo = _which("sudo")
        if not sudo:
            return PrivilegeState.PRIVILEGE_REQUIRED
        r = runner or SubprocessCommandRunner()
        try:
            completed = r.run([sudo, "-n", "true"], timeout=10.0)
            sudo_noninteractive = completed.returncode == 0
        except Exception:  # noqa: BLE001
            sudo_noninteractive = False

    if sudo_noninteractive:
        return PrivilegeState.NONINTERACTIVE_ELEVATION_AVAILABLE
    return PrivilegeState.PRIVILEGE_REQUIRED


def elevate_argv(argv: Sequence[str], privilege: PrivilegeState) -> list[str]:
    """Prefix with sudo -n when noninteractive elevation is the available path."""
    cmd = list(argv)
    if privilege == PrivilegeState.NONINTERACTIVE_ELEVATION_AVAILABLE:
        sudo = _which("sudo") or "sudo"
        return [sudo, "-n", *cmd]
    return cmd


def fingerprint_argv(argv: Sequence[str]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(list(argv), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def windows_extra_search_dirs() -> list[str]:
    """Bounded known locations for freshly installed Windows binaries."""
    if platform.system().lower() != "windows":
        return []
    dirs: list[str] = []
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    local_app = os.environ.get("LOCALAPPDATA")
    candidates = []
    if program_files:
        candidates.extend(
            [
                Path(program_files) / "Git" / "cmd",
                Path(program_files) / "Git" / "bin",
                Path(program_files) / "nodejs",
                Path(program_files) / "curl" / "bin",
            ]
        )
    if program_files_x86:
        candidates.extend(
            [
                Path(program_files_x86) / "Git" / "cmd",
                Path(program_files_x86) / "nodejs",
            ]
        )
    if local_app:
        candidates.append(Path(local_app) / "Programs" / "Git" / "cmd")
    for path in candidates:
        if path.is_dir():
            dirs.append(str(path))
    return dirs
