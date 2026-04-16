import os
import json
import re
from typing import Dict, List, Optional, Callable
from .code_downloader import get_code_structure, get_source_files, read_file_content
from .deps import get_llm_instance
from .interview_sandbox import get_sandbox_path
from langchain_core.messages import HumanMessage, SystemMessage


class CodeAnalysis:
    """代码分析结果模型"""
    def __init__(
        self,
        project_name: str = "",
        language: str = "",
        structure: Dict = None,
        key_files: List[Dict] = None,
        dependencies: Dict = None,
        summary: str = "",
        key_modules: List[str] = None,
        design_patterns: List[str] = None,
        tech_stack: List[str] = None
    ):
        self.project_name = project_name
        self.language = language
        self.structure = structure or {}
        self.key_files = key_files or []
        self.dependencies = dependencies or {}
        self.summary = summary
        self.key_modules = key_modules or []
        self.design_patterns = design_patterns or []
        self.tech_stack = tech_stack or []

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "project_name": self.project_name,
            "language": self.language,
            "structure": self.structure,
            "key_files": self.key_files,
            "dependencies": self.dependencies,
            "summary": self.summary,
            "key_modules": self.key_modules,
            "design_patterns": self.design_patterns,
            "tech_stack": self.tech_stack
        }


def detect_project_language(sandbox_id: str) -> str:
    """
    检测项目的主要编程语言

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        str: 检测到的编程语言
    """
    source_files = get_source_files(sandbox_id)
    if not source_files:
        return "Unknown"

    language_counts = {
        'Python': 0,
        'JavaScript': 0,
        'TypeScript': 0,
        'Java': 0,
        'Go': 0,
        'Rust': 0,
        'C++': 0,
        'C': 0,
        'C#': 0,
        'PHP': 0,
        'Ruby': 0
    }

    for filepath in source_files:
        if filepath.endswith('.py'):
            language_counts['Python'] += 1
        elif filepath.endswith('.js') or filepath.endswith('.jsx'):
            language_counts['JavaScript'] += 1
        elif filepath.endswith('.ts') or filepath.endswith('.tsx'):
            language_counts['TypeScript'] += 1
        elif filepath.endswith('.java') or filepath.endswith('.kt'):
            language_counts['Java'] += 1
        elif filepath.endswith('.go'):
            language_counts['Go'] += 1
        elif filepath.endswith('.rs'):
            language_counts['Rust'] += 1
        elif filepath.endswith('.cpp'):
            language_counts['C++'] += 1
        elif filepath.endswith('.c') or filepath.endswith('.h'):
            language_counts['C'] += 1
        elif filepath.endswith('.cs'):
            language_counts['C#'] += 1
        elif filepath.endswith('.php'):
            language_counts['PHP'] += 1
        elif filepath.endswith('.rb'):
            language_counts['Ruby'] += 1

    # 返回文件数量最多的语言
    detected_language = max(language_counts, key=language_counts.get)
    if language_counts[detected_language] == 0:
        return "Unknown"

    return detected_language


def extract_dependencies(sandbox_id: str, language: str) -> Dict:
    """
    提取项目依赖

    Args:
        sandbox_id: 沙箱 ID
        language: 编程语言

    Returns:
        dict: 依赖信息
    """
    sandbox_path = get_sandbox_path(sandbox_id)
    if not sandbox_path:
        return {}

    dependencies = {}

    # 根据语言查找依赖文件
    dependency_files = {
        'Python': ['requirements.txt', 'pyproject.toml', 'setup.py', 'Pipfile'],
        'JavaScript': ['package.json', 'yarn.lock', 'package-lock.json'],
        'TypeScript': ['package.json', 'yarn.lock', 'package-lock.json'],
        'Java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
        'Go': ['go.mod', 'go.sum'],
        'Rust': ['Cargo.toml', 'Cargo.lock'],
        'C++': ['CMakeLists.txt', 'vcpkg.json'],
        'C#': ['packages.config', '*.csproj'],
        'PHP': ['composer.json'],
        'Ruby': ['Gemfile']
    }

    target_files = dependency_files.get(language, [])

    for root, _, files in os.walk(sandbox_path):
        for file in files:
            if file in target_files:
                filepath = os.path.join(root, file)
                content = read_file_content(filepath, max_size=5000)
                if content:
                    dependencies[file] = content[:2000]  # 限制内容长度

    return dependencies


def get_key_files(sandbox_id: str, language: str, max_files: int = 5) -> List[Dict]:
    """
    获取关键的源代码文件

    Args:
        sandbox_id: 沙箱 ID
        language: 编程语言
        max_files: 最多返回的文件数量

    Returns:
        list: 关键文件列表，每个元素包含文件名和内容
    """
    source_files = get_source_files(sandbox_id)

    # 根据语言设置不同的文件优先级
    priority_keywords = {
        'Python': ['__init__', 'main', 'app', 'models', 'views', 'controllers', 'services', 'utils'],
        'JavaScript': ['index', 'main', 'app', 'component', 'service', 'controller', 'router'],
        'TypeScript': ['index', 'main', 'app', 'component', 'service', 'controller', 'router'],
        'Java': ['Application', 'Controller', 'Service', 'Repository', 'Model', 'Config'],
        'Go': ['main', 'handler', 'service', 'model', 'repository'],
        'Rust': ['main', 'lib', 'mod', 'handler', 'service']
    }

    keywords = priority_keywords.get(language, ['main', 'index', 'app'])

    # 优先选择包含关键词的文件
    prioritized_files = []
    other_files = []

    for filepath in source_files:
        basename = os.path.basename(filepath).lower()
        if any(keyword in basename for keyword in keywords):
            prioritized_files.append(filepath)
        else:
            other_files.append(filepath)

    # 混合优先级文件和其他文件
    selected_files = (prioritized_files[:max_files] +
                     other_files[:max(max_files - len(prioritized_files), 0)])

    # 读取文件内容
    key_files = []
    for filepath in selected_files:
        content = read_file_content(filepath, max_size=8000)
        if content:
            key_files.append({
                "filename": os.path.basename(filepath),
                "filepath": filepath,
                "content": content
            })

    return key_files


async def analyze_codebase_with_llm(
    sandbox_id: str,
    language: str,
    key_files: List[Dict],
    dependencies: Dict,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Dict:
    """
    使用 LLM 分析代码库

    Args:
        sandbox_id: 沙箱 ID
        language: 编程语言
        key_files: 关键文件列表

        dependencies: 依赖信息
        progress_callback: 进度回调函数

    Returns:
        dict: 分析结果
    """
    if progress_callback:
        progress_callback(50, "准备代码分析")

    # 构建代码摘要
    code_summary = f"项目编程语言: {language}\n\n"

    # 添加依赖信息
    if dependencies:
        code_summary += "项目依赖:\n"
        for dep_file, dep_content in dependencies.items():
            code_summary += f"\n--- {dep_file} ---\n{dep_content}\n"
        code_summary += "\n"

    # 添加关键文件内容
    if key_files:
        code_summary += "关键文件:\n"
        for file_info in key_files:
            code_summary += f"\n--- {file_info['filename']} ---\n"
            code_summary += file_info['content'] + "\n"

    # 使用 LLM 进行分析
    if progress_callback:
        progress_callback(60, "使用 LLM 分析代码")

    llm = await get_llm_instance()

    system_prompt = f"""你是一个专业的代码分析专家，擅长分析 {language} 代码库。

请分析提供的代码，重点关注以下方面：
1. 项目的主要功能和业务逻辑
2. 核心模块和类的设计
3. 使用的设计模式和架构特点
4. 技术栈和关键技术选择
5. 代码质量和潜在改进点

请以结构化的 JSON 格式返回分析结果，包含以下字段：
{{
  "project_name": "项目名称（从代码中推断）",
  "summary": "项目功能摘要（200-300字）",
  "key_modules": ["核心模块1", "核心模块2"],
  "design_patterns": ["使用的设计模式1", "设计模式2"],
  "tech_stack": ["技术栈1", "技术栈2"],
  "key_logic": ["关键逻辑点1", "关键逻辑点2"],
  "potential_questions": ["可以问的面试问题1", "面试问题2"]
}}
"""

    user_prompt = f"""请分析以下 {language} 代码库：

{code_summary[:10000]}  # 限制输入长度

请提供详细的代码分析结果。"""

    try:
        if progress_callback:
            progress_callback(70, "生成代码分析报告")

        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])

        # 解析 LLM 返回的 JSON
        content = response.content.strip()

        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_content = json_match.group()
            try:
                analysis_result = json.loads(json_content)
                return analysis_result
            except json.JSONDecodeError:
                pass

        # 如果 JSON 解析失败，返回原始文本
        return {
            "project_name": "Unknown",
            "summary": content[:500],
            "key_modules": [],
            "design_patterns": [],
            "tech_stack": [],
            "key_logic": [],
            "potential_questions": [],
            "raw_response": content
        }

    except Exception as e:
        print(f"LLM 代码分析失败: {str(e)}")
        return {
            "project_name": "Unknown",
            "summary": f"代码分析失败: {str(e)}",
            "key_modules": [],
            "design_patterns": [],
            "tech_stack": [],
            "key_logic": [],
            "potential_questions": []
        }


async def analyze_codebase(
    sandbox_id: str,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> CodeAnalysis:
    """
    分析代码库的主入口

    Args:
        sandbox_id: 沙箱 ID
        progress_callback: 进度回调函数

    Returns:
        CodeAnalysis: 代码分析结果
    """
    if progress_callback:
        progress_callback(10, "获取代码结构")

    # 获取代码结构
    structure = get_code_structure(sandbox_id)
    if not structure:
        raise ValueError("无法获取代码结构")

    if progress_callback:
        progress_callback(20, "检测编程语言")

    # 检测编程语言
    language = detect_project_language(sandbox_id)

    if progress_callback:
        progress_callback(30, "提取项目依赖")

    # 提取依赖
    dependencies = extract_dependencies(sandbox_id, language)

    if progress_callback:
        progress_callback(40, "识别关键文件")

    # 获取关键文件
    key_files = get_key_files(sandbox_id, language, max_files=8)

    # 使用 LLM 进行深度分析
    llm_analysis = await analyze_codebase_with_llm(
        sandbox_id, language, key_files, dependencies, progress_callback
    )

    if progress_callback:
        progress_callback(90, "整理分析结果")

    # 构建最终分析结果
    analysis = CodeAnalysis(
        project_name=llm_analysis.get("project_name", structure.get("name", "Unknown")),
        language=language,
        structure=structure,
        key_files=key_files,
        dependencies=dependencies,
        summary=llm_analysis.get("summary", ""),
        key_modules=llm_analysis.get("key_modules", []),
        design_patterns=llm_analysis.get("design_patterns", []),
        tech_stack=llm_analysis.get("tech_stack", [])
    )

    if progress_callback:
        progress_callback(100, "代码分析完成")

    return analysis


async def quick_code_summary(sandbox_id: str) -> str:
    """
    快速生成代码摘要（用于预览）

    Args:
        sandbox_id: 沙箱 ID

    Returns:
        str: 代码摘要
    """
    try:
        analysis = await analyze_codebase(sandbox_id)
        summary_parts = [
            f"项目名称: {analysis.project_name}",
            f"编程语言: {analysis.language}",
            f"共有 {len(analysis.key_files)} 个关键文件",
        ]

        if analysis.tech_stack:
            summary_parts.append(f"技术栈: {', '.join(analysis.tech_stack)}")

        if analysis.design_patterns:
            summary_parts.append(f"设计模式: {', '.join(analysis.design_patterns)}")

        if analysis.summary:
            summary_parts.append(f"\n项目摘要: {analysis.summary}")

        return "\n".join(summary_parts)

    except Exception as e:
        return f"代码摘要生成失败: {str(e)}"
