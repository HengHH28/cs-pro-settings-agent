import subprocess
import logging
from pathlib import Path
from langchain.tools import tool

logger = logging.getLogger("project")


# ============================================================
# 项目根目录
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 危险命令黑名单（子串匹配，大小写不敏感）
BLOCKED_COMMANDS = [
    "rm -rf",
    "rmdir /s",
    "rd /s",
    "del /f",
    "del /q",
    "remove-item",
    "format ",
    "diskpart",
    "shutdown",
    "taskkill",
    "drop table",
    "drop database",
]


# ============================================================
# 安全路径处理
# ============================================================

def get_safe_path(file_path: str) -> Path:
    """
    将用户提供的项目相对路径转换成安全的绝对路径。

    禁止访问 CS_Pro_Settings_Agent 项目目录之外的文件。
    """

    path = (PROJECT_ROOT / file_path).resolve()

    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError:
        raise ValueError("禁止访问项目目录之外的文件。")

    return path


# ============================================================
# 读取文件
# ============================================================

@tool
def read_project_file(file_path: str) -> str:
    """
    Read a source code file from the CS_Pro_Settings_Agent project.

    Input:
        Relative file path, for example:
        scraper/prosettings.py

    Return:
        The complete content of the file.
    """

    try:
        path = get_safe_path(file_path)

        if not path.exists():
            return f"文件不存在: {file_path}"

        if not path.is_file():
            return f"这不是一个文件: {file_path}"

        return path.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError:
        return f"无法使用 UTF-8 读取文件: {file_path}"

    except Exception as e:
        return f"读取文件失败: {str(e)}"


# ============================================================
# 搜索项目代码
# ============================================================

@tool
def search_project_code(keyword: str) -> str:
    """
    Search for a keyword in Python source files inside the project.

    Input:
        Keyword or function name.

    Example:
        scrape_prosettings

    Return:
        Matching files, line numbers and code lines.
    """

    results = []

    for path in PROJECT_ROOT.rglob("*.py"):

        # 忽略虚拟环境
        if "venv" in path.parts:
            continue

        try:
            content = path.read_text(
                encoding="utf-8"
            )

        except (UnicodeDecodeError, OSError):
            continue

        for line_number, line in enumerate(
            content.splitlines(),
            start=1
        ):

            if keyword.lower() in line.lower():

                relative_path = path.relative_to(
                    PROJECT_ROOT
                )

                results.append(
                    f"{relative_path}:{line_number}: {line.strip()}"
                )

    if not results:
        return f"没有找到关键词: {keyword}"

    return "\n".join(results)


# ============================================================
# 写入 / 修改文件
# ============================================================

@tool
def write_project_file(file_path: str, content: str):
    """
    Write or modify a file inside the current CS Pro Settings project.

    Args:
        file_path:
            Project-relative file path.

        content:
            Complete new content of the file.

    Returns:
        Result of the write operation.
    """

    try:
        target = get_safe_path(file_path)

        # 创建父目录
        target.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        # 写入文件
        target.write_text(
            content,
            encoding="utf-8"
        )

        return f"Successfully wrote file: {file_path}"

    except Exception as e:
        return f"Error writing file: {e}"


# ============================================================
# 删除文件
# ============================================================

@tool
def delete_project_file(file_path: str):
    """
    Delete a file inside the CS_Pro_Settings_Agent project.

    This tool is mainly intended for removing temporary files
    created during debugging or testing.

    Input:
        Project-relative file path.

    Example:
        _debug_prosettings.py
    """

    try:
        target = get_safe_path(file_path)

        if not target.exists():
            return f"文件不存在，无需删除: {file_path}"

        if not target.is_file():
            return f"不是普通文件，拒绝删除: {file_path}"

        target.unlink()

        return f"Successfully deleted file: {file_path}"

    except Exception as e:
        return f"Error deleting file: {e}"


# ============================================================
# 执行项目命令
# ============================================================

@tool
def run_project_command(command: str, confirm: bool = False):
    """
    Run a command inside the CS_Pro_Settings_Agent project directory.

    Args:
        command: Command to execute.
        confirm: Must be True to execute. Only set True when the user
                 explicitly asked to run the command.

    Returns:
        Command output and exit code.
    """

    # 危险命令黑名单
    for pattern in BLOCKED_COMMANDS:
        if pattern in command.lower():
            return f"Error: command blocked by safety policy ({pattern})."

    if not confirm:
        return (
            "Error: refused to run command without confirmation. "
            "Set confirm=True only when the user explicitly asked to run it."
        )

    logger.info("run command: %s", command)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60
        )

        output = ""

        if result.stdout:
            output += "STDOUT:\n"
            output += result.stdout

        if result.stderr:
            output += "\nSTDERR:\n"
            output += result.stderr

        output += f"\nEXIT CODE: {result.returncode}"

        return output

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."

    except Exception as e:
        return f"Error running command: {e}"
