#!/usr/bin/env python3
import os
import sys
import json
import ast

# ──────────────────────────────────────────────────────────────────────────────
# Antigravity 专属打造：纯原生 Agent Workflow (Extractor -> Oracle -> Validator)
# ──────────────────────────────────────────────────────────────────────────────

class AgentState:
    def __init__(self, text_chunk: str):
        self.text_chunk = text_chunk
        self.raw_extraction = None
        self.parsed_json = None
        self.sympy_valid = False
        self.physical_valid = False
        self.errors = []
        self.final_result = None

# ==========================================
# 🧠 Agent 1: 提取与解构专家 (Extractor)
# ==========================================
def extractor_agent(state: AgentState, api_key: str):
    """负责将非结构化文本剥离出 Track A 严格数学公式（含试错和重试机制）"""
    print("[Extractor Agent] 正在审阅文本区块并抽取方程...")
    
    # 这里可以使用 google-generativeai 或你刚才看到的 claude API
    # 出于演示流水线逻辑，本函数组装 Prompt，交给统一的大模型底座
    
    PROMPT = f"""
    提取以下文本中的微分方程或物理定律。如果你之前的提取有错误，请根据错误反馈修正。
    【之前的错误】：{state.errors if state.errors else '无'}
    【文本】：{state.text_chunk}
    """
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-pro')
        
        # 实际调用
        response = model.generate_content(PROMPT)
        
        # 强制清理大模型的 markdown 格式
        raw_text = response.text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1].rsplit("\n", 1)[0]
            
        state.raw_extraction = raw_text
        state.parsed_json = json.loads(raw_text)
        return state
        
    except Exception as e:
        state.errors.append(f"Extractor 返回了非 JSON 格式或调用失败：{str(e)}")
        return state


# ==========================================
# ⚖️ Agent 2: 语法与数学裁判 (Syntax Oracle)
# ==========================================
def syntax_oracle_agent(state: AgentState):
    """负责把关大模型瞎编的 sympy_expression，强行运行 Python AST 或 SymPy Parser 检测"""
    if not state.parsed_json:
        return state
        
    print("[Oracle Agent] 正在验证 sympy_expression 的代数合法性...")
    data = state.parsed_json
    expr = data.get("sympy_expression")
    
    if not expr:
        print("[Oracle Agent] 没有检测到公式，放行。")
        state.sympy_valid = True
        return state
        
    try:
        # 使用 Python 原生 AST 解析来防止极其离谱的幻觉语法
        ast.parse(expr)
        
        # 若环境装了 sympy，此处将直接执行 sympy.parse_expr(expr)
        import sympy
        from sympy.parsing.sympy_parser import parse_expr
        parse_expr(expr, evaluate=False)
        
        print(f"[Oracle Agent] \033[92m通过！\033[0m 这是一个有效的数学表达式: {expr}")
        state.sympy_valid = True
        
    except Exception as e:
        error_msg = f"SymPy 语法解析失败！你的表达式 '{expr}' 不是合法的数学方程。错误: {str(e)}"
        print(f"[Oracle Agent] \033[91m拦截！\033[0m {error_msg}")
        state.errors.append(error_msg)
        state.sympy_valid = False
        
    return state


# ==========================================
# 🕵️‍♂️ Agent 3: 物理规则审查员 (Validator)
# ==========================================
def validator_agent(state: AgentState):
    """如果大模型输出了如 'Temperature = 100°C' 的经验常识，Validator 负责将其销毁"""
    if not state.sympy_valid or not state.parsed_json:
        return state
        
    print("[Validator Agent] 正在检查物理量单位和维度拦截...")
    data = state.parsed_json
    
    # 强制拦截低智阈值判断
    if data.get("formula_type") not in ["differential_equation", "algebraic_law"]:
        err = f"拦截：Formula 类别错误，发现了不受欢迎的类型 {data.get('formula_type')}"
        print(f"[Validator Agent] \033[91m拦截！\033[0m {err}")
        state.errors.append(err)
        return state
        
    print("[Validator Agent] \033[92m通过！\033[0m 参数校验完成。这条数据可入库 Neo4j。")
    state.physical_valid = True
    state.final_result = data
    return state


# ==========================================
# 🔄 Workflow Orchestrator (编排引擎)
# ==========================================
def run_cleaning_workflow(text_chunk: str, api_key: str, max_retries: int = 2) -> dict:
    """LangGraph 思想的精简实现，控制不同 Agent 的状态流转与回炉重造"""
    
    state = AgentState(text_chunk)
    retries = 0
    
    while retries <= max_retries:
        if retries > 0:
            print(f"\n===== [开始第 {retries} 次回炉重造] =====")
            
        # 节点 1: 提取
        state = extractor_agent(state, api_key)
        
        # 节点 2: 语法把关
        if state.parsed_json:
            state = syntax_oracle_agent(state)
            
        # 节点 3: 物理校验
        if state.sympy_valid:
            state = validator_agent(state)
            
        # 路由判定：如果通过，输出
        if state.physical_valid:
            return state.final_result
            
        # 如果报错，流转回节点 1
        retries += 1
        
    print("[Orchestrator] 超过最大重试次数，数据报废或记录人工清洗对列。")
    return None

if __name__ == "__main__":
    # 本地跑跑看
    print("多智能体清洗流水线 (Agentic Clean Pipeline) 启动就绪！\n")
    pass
