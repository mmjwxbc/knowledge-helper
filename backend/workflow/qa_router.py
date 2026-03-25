from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from langchain_core.output_parsers import PydanticOutputParser, StrOutputParser
from langchain_core.runnables import RunnableBranch, RunnableLambda
from langchain_deepseek import ChatDeepSeek
import os
import asyncio
from enum import Enum

# ============ 数据模型定义 ============

class ContentCategory(str, Enum):
    ISOLATED_QUESTION = "isolated_question"      # 单独的问题，无答案
    FACT_DESCRIPTION = "fact_description"        # 事实描述，需要生成问题
    QA_PAIR = "qa_pair"                          # 已有问答对，需要优化
    MULTI_QA = "multi_qa"                        # 多个问答混合

class QAItem(BaseModel):
    question: str = Field(description="清晰、具体的问题")
    answer: str = Field(description="简洁、准确的答案")
    tags: List[str] = Field(description="3-5个相关标签", default_factory=list)
    confidence: float = Field(description="置信度 0-1", default=0.9)
    source_type: ContentCategory = Field(description="内容来源类型")

class RefinedOutput(BaseModel):
    items: List[QAItem] = Field(description="提取的所有Q&A项")
    total_count: int = Field(description="识别出的问题数量")
    routing_decision: str = Field(description="路由决策说明")

# ============ 阶段1: 智能意图分类器 ============

class IntentClassifier:
    """使用 Few-Shot 示例进行精确意图识别"""
    
    # 定义 Few-Shot 示例
    examples = [
        {
            "input": "Python中的GIL是什么？它为什么会成为多线程的瓶颈？",
            "analysis": "包含明确问题词'是什么'、'为什么'，且没有现成答案",
            "category": "isolated_question"
        },
        {
            "input": "Docker容器化技术通过操作系统级虚拟化实现应用隔离。每个容器共享主机内核但拥有独立的文件系统、进程空间和网络接口。",
            "analysis": "纯事实陈述，包含技术定义和解释，无明确问题",
            "category": "fact_description"
        },
        {
            "input": "Q: 什么是RESTful API?\nA: RESTful API是一种基于HTTP协议的设计风格，使用URL定位资源，HTTP方法定义操作（GET/POST/PUT/DELETE），状态码表示结果。",
            "analysis": "明确的问答对格式，Q和A标签清晰",
            "category": "qa_pair"
        },
        {
            "input": "问题1: 如何优化SQL查询？\n答案1: 使用索引、避免SELECT *、优化JOIN操作。\n问题2: 什么是数据库范式？\n答案2: 范式是数据库设计的规范，包括1NF、2NF、3NF等。",
            "analysis": "包含多个问题-答案组合，结构清晰",
            "category": "multi_qa"
        },
        {
            "input": "帮我解释一下机器学习中的过拟合现象",
            "analysis": "祈使句形式的隐性提问，无现成答案",
            "category": "isolated_question"
        }
    ]
    
    def __init__(self, llm):
        self.llm = llm
        self.parser = PydanticOutputParser(pydantic_object=CategoryResult)
        
    def create_classifier_chain(self):
        # Few-Shot 示例模板
        example_prompt = ChatPromptTemplate.from_messages([
            ("human", "内容: {input}\n分析: {analysis}"),
            ("ai", "{category}")
        ])
        
        few_shot_prompt = FewShotChatMessagePromptTemplate(
            example_prompt=example_prompt,
            examples=self.examples,
        )
        
        # 主提示词
        system_template = """你是一个专业的内容分类专家。分析用户输入的内容，判断其属于以下哪种类型：

            1. **isolated_question**: 孤立问题 - 只有问题没有答案（如"什么是XXX？"、"如何YYY？"）
            2. **fact_description**: 事实描述 - 纯信息陈述，没有明确问题（如技术文档、概念解释）
            3. **qa_pair**: 单问答对 - 包含一个问题和对应的答案
            4. **multi_qa**: 多问答混合 - 包含多个问题及对应答案

            分类规则：
            - 优先检测问答对格式（Q:/A:、问题/答案、Q1/A1等标记）
            - 检测疑问词（什么、如何、为什么、是否、怎么）判断是否为问题
            - 无问句标记但有明确信息量的归为事实描述

            {format_instructions}

            只需返回JSON格式的分类结果，不要其他解释。"""

        final_prompt = ChatPromptTemplate.from_messages([
            ("system", system_template),
            few_shot_prompt,
            ("human", "内容: {content}\n请分类：")
        ])
        final_prompt = final_prompt.partial(
        format_instructions=self.parser.get_format_instructions()
    )
        return final_prompt | self.llm | self.parser

class CategoryResult(BaseModel):
    category: ContentCategory
    reasoning: str
    estimated_items: int = Field(description="估计包含的问答对数量", default=1)

# ============ 阶段2: 内容提取处理器 ============

class ContentProcessor:
    """针对不同类型内容的专业处理器"""
    
    def __init__(self, llm):
        self.llm = llm
        
    def create_isolated_question_processor(self):
        """处理孤立问题：生成高质量答案"""
        prompt = ChatPromptTemplate.from_template("""你是一个专业知识助手。基于用户的问题，生成一个准确、全面的答案。

            用户问题: {content}

            要求：
            1. 答案应该直接回答问题，避免冗余
            2. 使用清晰的结构（如需要可分点说明）
            3. 包含关键概念的解释
            4. 答案长度控制在200-500字

            {format_instructions}

            如果提供了反馈，请优先遵循反馈要求：
            {feedback}

            输出JSON格式。"""
        )

        parser = PydanticOutputParser(pydantic_object=QAItem)
        return prompt.partial(
            format_instructions=parser.get_format_instructions()
        ) | self.llm | parser

    def create_fact_processor(self):
        """处理事实描述：生成探索性问题+总结答案"""
        prompt = ChatPromptTemplate.from_template("""将以下事实描述转换为高质量的Q&A对。

            原始内容: {content}

            任务：
            1. 根据内容生成2-3个最能考察核心知识点的问题（使用5W1H方法）
            2. 为每个问题提供基于原文的准确答案
            3. 确保问题具有启发性，不是简单的事实复述

            {format_instructions}

            反馈要求（如有）: {feedback}

            输出包含多个QAItem的JSON数组格式。"""
        )

        parser = PydanticOutputParser(pydantic_object=RefinedOutput)
        return prompt.partial(
            format_instructions=parser.get_format_instructions()
        ) | self.llm | parser

    def create_qa_optimizer(self):
        """优化现有问答对"""
        prompt = ChatPromptTemplate.from_template("""优化以下问答对，使其更加清晰、准确、专业。

            原始内容: {content}

            优化要求：
            1. **问题优化**：使其更具体、明确，去除歧义
            2. **答案优化**：结构清晰，重点突出，补充必要细节
            3. **标签生成**：3-5个关键词标签，涵盖主题、技术、领域
            4. **质量检查**：确保答案直接对应问题，无跑题

            {format_instructions}

            用户反馈（优先遵循）: {feedback}

            输出JSON格式。"""
        )

        parser = PydanticOutputParser(pydantic_object=QAItem)
        return prompt.partial(
            format_instructions=parser.get_format_instructions()
        ) | self.llm | parser

    def create_multi_qa_processor(self):
        """处理多问答混合内容"""
        prompt = ChatPromptTemplate.from_template("""从以下混合内容中提取并优化所有问答对。

            原始内容: {content}

            处理步骤：
            1. **识别分割**：识别内容中包含的各个独立问题（注意Q1/A1、问题1/答案1等标记）
            2. **逐一优化**：对每个问答对进行优化
            3. **去重合并**：相似问题合并，保留最佳答案
            4. **排序整理**：按逻辑顺序排列

            {format_instructions}

            用户反馈: {feedback}

            输出包含所有QAItem的JSON数组。"""
        )

        parser = PydanticOutputParser(pydantic_object=RefinedOutput)
        return prompt.partial(
            format_instructions=parser.get_format_instructions()
        ) | self.llm | parser

# ============ 阶段3: 路由 orchestrator ============

class QARouter:
    """智能路由协调器"""
    
    def __init__(self, llm):
        self.llm = llm
        self.classifier = IntentClassifier(llm)
        self.processor = ContentProcessor(llm)
        
    async def route_and_process(self, text: str, feedback: str = None) -> RefinedOutput:
        """完整的路由处理流程"""
        
        # Step 1: 意图分类
        classifier_chain = self.classifier.create_classifier_chain()
        category_result = await classifier_chain.ainvoke({"content": text[:2000]})
        
        print(f"[路由决策] 分类: {category_result.category}, 理由: {category_result.reasoning}")
        
        # Step 2: 根据分类路由到对应处理器
        processor_map = {
            ContentCategory.ISOLATED_QUESTION: self.processor.create_isolated_question_processor(),
            ContentCategory.FACT_DESCRIPTION: self.processor.create_fact_processor(),
            ContentCategory.QA_PAIR: self.processor.create_qa_optimizer(),
            ContentCategory.MULTI_QA: self.processor.create_multi_qa_processor()
        }
        
        selected_processor = processor_map.get(category_result.category)
        
        # Step 3: 执行处理
        try:
            result = await selected_processor.ainvoke({
                "content": text[:4000],  # 保留更多上下文
                "feedback": feedback or "无特殊反馈"
            })
            
            # 统一输出格式
            if isinstance(result, QAItem):
                output = RefinedOutput(
                    items=[result],
                    total_count=1,
                    routing_decision=f"{category_result.category.value}: {category_result.reasoning}"
                )
            else:
                output = result
                output.routing_decision = f"{category_result.category.value}: {category_result.reasoning}"
                
            return output
            
        except Exception as e:
            print(f"处理错误: {e}")
            # Fallback: 使用通用处理器
            return await self._fallback_process(text, feedback, category_result)
    
    async def _fallback_process(self, text: str, feedback: str, category_result: CategoryResult) -> RefinedOutput:
        """降级处理"""
        generic_prompt = ChatPromptTemplate.from_template("""从以下内容中提取或生成问答对：
                                                            
            内容: {content}
            
            尽可能提取清晰的问题和答案，如果只有问题就生成答案，如果只有事实就生成问题和答案。
            
            {format_instructions}"""
        )
        
        parser = PydanticOutputParser(pydantic_object=RefinedOutput)
        chain = generic_prompt.partial(
            format_instructions=parser.get_format_instructions()
        ) | self.llm | parser
        
        return await chain.ainvoke({
            "content": text[:3000],
            "feedback": feedback or ""
        })

# ============ 使用示例 ============

async def main():
    # 初始化模型
    llm = ChatDeepSeek(
        model="deepseek-chat",  # 或 DeepSeek/GLM 等
        temperature=0.3,      # 分类用低温度保证稳定
        api_key="sk-a1bc19bfbb3848659b05a24d57ccb9ef"
    )
    
    router = QARouter(llm)
    
    # 测试不同类型输入
    test_cases = [
        # 孤立问题
#         "什么是Kubernetes中的Pod，它和容器有什么区别？",
        
#         # 事实描述
#         """微服务架构是一种将单一应用程序划分成一组小的服务的方法。每个服务运行在自己的进程中，服务间通过轻量级机制（通常是HTTP API）通信。每个服务围绕业务能力构建，能够独立部署。""",
        
#         # 已有问答对
#         """Q: 什么是负载均衡？
# A: 负载均衡是将网络流量分配到多个服务器的技术，防止单点故障，提高系统可用性。常见算法有轮询、最少连接、IP哈希等。""",
        
#         # 多问答混合
#         """问题1: 什么是CI/CD？
# 答案1: CI/CD是持续集成和持续部署的缩写，指通过自动化流程频繁地将代码变更部署到生产环境。

# 问题2: Git和SVN有什么区别？
# 答案2: Git是分布式版本控制系统，每个开发者有完整仓库副本；SVN是集中式，所有操作依赖中央服务器。""",
            """
            OCR 结果有噪声或错误时，你是怎么做纠错或提升解析质量的？
            多模态检索中，图像和文本向量不在同一空间时，如何实现对齐？
            Agent 中长短期记忆如何设计？各自存什么，怎么触发读取？
            多轮对话中，如果不同轮次的记忆发生冲突，你如何处理？
            用户情绪异常（投诉、愤怒）时，Agent 如何在不中断主流程的情况下进行干预？
            长文档为什么一定要切 chunk 再做向量化？不切会有什么问题？
            chunk切分时为什么要有重叠区域？比例一般怎么确定？
            稠密向量和稀疏向量的区别是什么？各自适合什么场景？
            是否做过关键词召回和向量召回的融合？具体怎么做的？
            向量检索中 Top-K 设置过大或过小分别会带来什么问题？
            余弦相似度和欧氏距离在高维空间中的差异是什么？实际怎么选？
            为什么需要 rerank 模型？它解决了向量召回的哪些问题？
            rerank之后的截断策略是怎么设计的？为什么选这个 K 值？
            文档发生局部更新时，如何做增量索引而不是全量重建？
            RAG 中如果没有召回到相关知识，如何约束模型避免胡编？
            HyDE 在 query 模糊时是如何提升召回效果的？
            超长上下文模型出现后，RAG 架构的必要性是否会下降？
            """

    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*50}")
        print(f"测试案例 {i}:")
        print(f"输入: {test[:100]}...")
        
        result = await router.route_and_process(test)
        
        print(f"\n识别到 {result.total_count} 个Q&A项:")
        for idx, item in enumerate(result.items, 1):
            print(f"\n[{idx}] {item.question}")
            print(f"答: {item.answer[:150]}...")
            print(f"标签: {', '.join(item.tags)}")
            print(f"置信度: {item.confidence}")

if __name__ == "__main__":
    asyncio.run(main())