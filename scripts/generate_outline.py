import ast
from pathlib import Path

# Setup paths relative to the project root
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
OUTLINE_FILE = PROJECT_ROOT / "docs" / "AST_OUTLINE.md"
FILE_TREE_FILE = PROJECT_ROOT / "docs" / "FILE_TREE.txt"

# Exact folder and file names to ignore
IGNORE_NAMES = {
    # System & Version Control
    ".git", ".github", ".DS_Store",

    # Caches & Environment Directories
    "__pycache__", ".mypy_cache", ".pytest_cache", ".venv", "venv", "node_modules",

    # Build Artifacts & Summaries
    "biohunter.egg-info", "dist", "build", "summaries", "snapshots",

    # Databases & Heavy Output Files (keep the tree lightweight for AI)
    "data", "reports", "biohunter.db"
}

def should_ignore(path: Path) -> bool:
    """Returns True if the file or folder name should be excluded from the tree."""
    if path.name in IGNORE_NAMES:
        return True
    if path.name.startswith(".") and path.name not in {".env.example", ".gitignore", ".pre-commit-config.yaml", ".context"}:
        return True
    if path.name.startswith("{"):
        return True
    return False

def generate_file_tree():
    """Generates a clean text representation of the repository file tree."""
    lines = ["# Repository File Tree", ""]

    def walk_dir(directory: Path, prefix: str = ""):
        entries = sorted(
            [e for e in directory.iterdir() if not should_ignore(e)],
            key=lambda x: (x.is_file(), x.name.lower())
        )

        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                walk_dir(entry, prefix + extension)

    walk_dir(PROJECT_ROOT)

    FILE_TREE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Ensure file ends with a trailing newline to pass end-of-file-fixer
    content = "\n".join(lines).strip() + "\n"
    FILE_TREE_FILE.write_text(content, encoding="utf-8")
    print(f"Updated File Tree at {FILE_TREE_FILE}")

def _format_default_val(default_node):
    """Safely converts AST default value nodes into human-readable strings."""
    try:
        return ast.unparse(default_node)
    except Exception:
        return "..."

def extract_file_ast_details(py_path: Path, relative_path: Path) -> list[str]:
    """Parses a single Python file and extracts rich structural detail."""
    raw_lines = [f"## `{relative_path}`", "```python"]

    try:
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as e:
        raw_lines.extend([f"# Error parsing file: {e}", "```", ""])
        return [l.rstrip() for l in raw_lines]

    docstring = ast.get_docstring(tree)
    if docstring:
        for line in docstring.strip().splitlines():
            raw_lines.append(f"# {line}")
        raw_lines.append("")

    def format_function_signature(node, is_method=False):
        args_parts = []
        defaults = node.args.defaults
        num_args = len(node.args.args)
        defaults_offset = num_args - len(defaults)

        for idx, arg in enumerate(node.args.args):
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            if idx >= defaults_offset:
                default_node = defaults[idx - defaults_offset]
                arg_str += f"={_format_default_val(default_node)}"
            args_parts.append(arg_str)

        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            if default:
                arg_str += f"={_format_default_val(default)}"
            args_parts.append(arg_str)

        ret_type = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        prefix = "    def " if is_method else "def "
        async_prefix = "async " if isinstance(node, (ast.AsyncFunctionDef,)) else ""
        return f"{prefix}{async_prefix}{node.name}({', '.join(args_parts)}){ret_type}:"

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and (target.id.isupper() or not target.id.startswith("_")):
                    raw_lines.append(f"{target.id} = {ast.unparse(node.value)}")
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                val = f" = {ast.unparse(node.value)}" if node.value else ""
                raw_lines.append(f"{node.target.id}: {ast.unparse(node.annotation)}{val}")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            raw_lines.append(format_function_signature(node))
            fn_doc = ast.get_docstring(node)
            if fn_doc:
                first_line = fn_doc.strip().splitlines()[0]
                raw_lines.append(f'    """{first_line}"""')
            raw_lines.extend(["    ...", ""])

        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            base_str = f"({', '.join(bases)})" if bases else ""
            raw_lines.append(f"class {node.name}{base_str}:")

            cls_doc = ast.get_docstring(node)
            if cls_doc:
                first_line = cls_doc.strip().splitlines()[0]
                raw_lines.append(f'    """{first_line}"""')

            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            raw_lines.append(f"    {target.id} = {ast.unparse(item.value)}")
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    val = f" = {ast.unparse(item.value)}" if item.value else ""
                    raw_lines.append(f"    {item.target.id}: {ast.unparse(item.annotation)}{val}")
                elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    raw_lines.append(format_function_signature(item, is_method=True))
                    m_doc = ast.get_docstring(item)
                    if m_doc:
                        first_line = m_doc.strip().splitlines()[0]
                        raw_lines.append(f'        """{first_line}"""')
                    raw_lines.extend(["        ...", ""])
            raw_lines.append("")

    raw_lines.extend(["```", ""])
    return raw_lines

def generate_ast_outline():
    """Extracts enriched function/class signatures, constants, and docstrings."""
    OUTLINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    outline_lines = [
        "# Project AST Outline",
        "> Auto-generated high-detail code skeleton for AI context.",
        ""
    ]

    if not SRC_DIR.exists():
        print(f"Warning: {SRC_DIR} directory does not exist.")
        return

    for py_path in sorted(SRC_DIR.rglob("*.py")):
        if any(should_ignore(part) for part in py_path.parents):
            continue

        relative_path = py_path.relative_to(PROJECT_ROOT)
        outline_lines.extend(extract_file_ast_details(py_path, relative_path))

    # Clean every single line by trimming trailing spaces explicitly
    cleaned_lines = [line.rstrip() for line in outline_lines]
    content = "\n".join(cleaned_lines).strip() + "\n"

    OUTLINE_FILE.write_text(content, encoding="utf-8")
    print(f"Updated Detailed AST Outline at {OUTLINE_FILE}")

if __name__ == "__main__":
    generate_file_tree()
    generate_ast_outline()
