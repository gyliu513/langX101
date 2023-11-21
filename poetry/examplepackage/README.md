让我们通过一个简单的例子来展示如何使用 Poetry 完成一个 Python 包的本地构建和发布。我们将创建一个名为 "examplepackage" 的示例 Python 包，并通过 Poetry 进行管理和发布。

## 步骤 1: 安装 Poetry
如果你还没有安装 Poetry，请先安装它。可以通过以下命令进行安装：

```bash
curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python -
```

## 步骤 2: 创建新项目
使用 Poetry 创建一个新项目。在命令行中运行：

```bash
poetry new examplepackage
```

这将创建一个名为 examplepackage 的新目录，并包括一些初始文件和文件夹，包括 pyproject.toml 文件和源代码文件夹。

## 步骤 3: 编辑 pyproject.toml 文件

编辑 pyproject.toml 文件，为你的包添加详细信息。例如：

```toml
[tool.poetry]
name = "examplepackage"
version = "0.1.0"
description = "A simple example package"
authors = ["Your Name <you@example.com>"]

[tool.poetry.dependencies]
python = "^3.8"

[tool.poetry.dev-dependencies]
pytest = "^5.2"
```

## 步骤 4: 编写包代码
在 examplepackage 文件夹中编写你的包代码。例如，在 examplepackage/__init__.py 中添加一些简单的功能：

```python
# examplepackage/__init__.py

def greet(name):
    return f"Hello, {name}!"
```

## 步骤 5: 构建包

在项目根目录（包含 pyproject.toml 的目录）中运行以下命令来构建你的包：

```bash
poetry build
```

这将在 dist 目录下创建 wheel 和 source 分发文件。

## 步骤 6: 在本地安装包

使用 pip 安装构建的包。首先，确保你的虚拟环境（如果你正在使用）是活跃的，然后运行：

```bash
pip install dist/examplepackage-0.1.0-py3-none-any.whl
```

## 步骤 7: 测试包

在 Python 解释器中或者在一个新的 Python 脚本中测试你的包是否正确安装和工作：

```python
from examplepackage.instrument.watsonx import greet

print(greet("World"))
```

如果一切正常，你应该看到输出 "Hello, World!"。

## 步骤 8: 清理和维护
如果你需要对包进行修改，可以更新代码，然后重复构建和安装步骤。
如果你更新了包版本，请确保在 pyproject.toml 文件中更新版本号。
**注意**
在进行本地测试时，使用虚拟环境是一个好习惯。这样可以保证你的测试环境干净，并且不会影响到其他项目或系统级的 Python 安装。
如果你计划将包发布到 PyPI 或其他远程仓库，请确保更新所有必要的元数据和文档，并遵循任何相关的最佳实践。
通过这个流程，你可以使用 Poetry 管理你的 Python 包的完整生命周期，从创建、构建到本地发布和测试。
