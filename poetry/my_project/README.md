# 使用 Poetry 的 Python 项目管理

`Poetry` 是一款为 Python 项目提供依赖管理和打包功能的工具，它以声明式的配置和简单直观的方式，帮助开发者高效地管理项目。以下是 `Poetry` 的主要功能及基本使用示例。

## Poetry 的工作原理:

1. **依赖管理**: 
   - `Poetry` 使用 `pyproject.toml` 文件来管理项目的依赖关系。添加或删除依赖时，`Poetry` 会自动更新 `pyproject.toml` 和 `poetry.lock` 文件，后者锁定了依赖的精确版本。
   - 它具有依赖解析器，能确保所有依赖和子依赖的版本之间保持兼容，避免版本冲突。

2. **环境隔离**:
   - `Poetry` 为每个项目创建独立的虚拟环境，确保项目依赖不会影响系统或其他项目的运行。

3. **包管理**:
   - `Poetry` 可帮助构建和发布 Python 包。它会读取 `pyproject.toml` 文件中的信息，生成必要的元数据，并将包打包为可分发的格式。

4. **命令行工具**:
   - `Poetry` 提供了一系列命令行工具，便于管理项目，例如添加或删除依赖、安装依赖、运行脚本等。

## 示例:

假设你想创建一个新的 Python 项目，并使用 `requests` 库。下面是如何使用 `Poetry` 来设置和管理这个项目的步骤：

1. **安装 Poetry**:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. **创建一个新项目:**:
   ```bash
   poetry new my_project
   cd my_project
   ```

3. **添加依赖**:
    ```bash
    poetry add requests
    ```

4. **写代码：**:

创建一个名为 main.py 的文件，并在 my_project 目录中添加以下代码：

     ```python
     import requests

     def fetch_data():
         response = requests.get("https://jsonplaceholder.typicode.com/posts/1")
         print(response.json())

     if __name__ == "__main__":
        fetch_data()
     ```
5. **运行项目**：

    ```bash
    poetry run python main.py
    ```

以上步骤展示了如何创建和管理一个使用 Poetry 的 Python 项目，并运行了一个简单示例程序。在此过程中，Poetry 为项目创建了一个虚拟环境，并管理了 requests 库的依赖关系。