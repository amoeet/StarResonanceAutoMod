# module_optimizer.py

import logging
import os
import random
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from logging_config import get_logger
from module_types import (
    ModuleInfo, ModuleType, ModuleAttrType, ModuleCategory,
    MODULE_CATEGORY_MAP, ATTR_THRESHOLDS, BASIC_ATTR_POWER_MAP, SPECIAL_ATTR_POWER_MAP,
    TOTAL_ATTR_POWER_MAP, BASIC_ATTR_IDS, SPECIAL_ATTR_IDS, ATTR_NAME_TYPE_MAP
)

# 获取日志器
logger = get_logger(__name__)


# --- 属性分类定义 ---
PHYSICAL_ATTRIBUTES = {"力量加持", "敏捷加持", "攻速专注"}
MAGIC_ATTRIBUTES = {"智力加持", "施法专注"}
ATTACK_ATTRIBUTES = {"特攻伤害", "精英打击", "力量加持", "敏捷加持", "智力加持"}
GUARDIAN_ATTRIBUTES = {"抵御魔法", "抵御物理"}
SUPPORT_ATTRIBUTES = {"特攻治疗加持", "专精治疗加持"}


@dataclass
class ModuleSolution:
    """模组搭配解"""
    modules: List[ModuleInfo]
    score: float
    attr_breakdown: Dict[str, int]
    optimization_score: float = 0.0


class ModuleOptimizer:
    """模组搭配优化器"""
    
    def __init__(self):
        """初始化模组搭配优化器"""
        self.logger = logger
        self._result_log_file = None
        self.local_search_iterations = 30
        self.max_solutions = 60
        self.prefilter_top_n_per_attr = 30
        self.prefilter_top_n_total_value = 50
        self.local_search_sample_size = 40
        # +++ 新增：多种子生成的数量 +++
        self.num_greedy_seeds = 5 # 每次尝试生成5个种子，并从中择优

    def _get_current_log_file(self) -> Optional[str]:
        try:
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, logging.FileHandler):
                    return handler.baseFilename
            return None
        except Exception as e:
            self.logger.warning(f"无法获取日志文件路径: {e}")
            return None
    
    def _log_result(self, message: str):
        try:
            if self._result_log_file is None:
                self._result_log_file = self._get_current_log_file()
            
            if self._result_log_file and os.path.exists(self._result_log_file):
                with open(self._result_log_file, 'a', encoding='utf-8') as f:
                    f.write(message + '\n')
        except Exception as e:
            self.logger.warning(f"记录筛选结果失败: {e}")
    
    def get_module_category(self, module: ModuleInfo) -> ModuleCategory:
        return MODULE_CATEGORY_MAP.get(module.config_id, ModuleCategory.ATTACK)
    
    def prefilter_modules(self, modules: List[ModuleInfo]) -> List[ModuleInfo]:
        self.logger.info(f"开始预筛选，原始模组数量: {len(modules)}")
        if not modules: return []

        candidate_modules = set()
        attr_modules = {}
        for module in modules:
            for part in module.parts:
                attr_name = part.name
                if attr_name not in attr_modules: attr_modules[attr_name] = []
                attr_modules[attr_name].append((module, part.value))
        
        for attr_name, module_values in attr_modules.items():
            sorted_by_attr = sorted(module_values, key=lambda x: x[1], reverse=True)
            top_modules = [item[0] for item in sorted_by_attr[:self.prefilter_top_n_per_attr]]
            candidate_modules.update(top_modules)

        sorted_by_total_value = sorted(modules, key=lambda m: sum(p.value for p in m.parts), reverse=True)
        top_generalists = sorted_by_total_value[:self.prefilter_top_n_total_value]
        candidate_modules.update(top_generalists)
        
        filtered_modules = list(candidate_modules)
        self.logger.info(f"预筛选完成，候选池数量: {len(filtered_modules)}")
        return filtered_modules

    def calculate_combat_power(self, modules: List[ModuleInfo]) -> Tuple[int, Dict[str, int]]:
        attr_breakdown = {}
        for module in modules:
            for part in module.parts:
                attr_breakdown[part.name] = attr_breakdown.get(part.name, 0) + part.value
        
        threshold_power, total_attr_value = 0, sum(attr_breakdown.values())
        for attr_name, attr_value in attr_breakdown.items():
            max_level = sum(1 for threshold in ATTR_THRESHOLDS if attr_value >= threshold)
            if max_level > 0:
                attr_type = ATTR_NAME_TYPE_MAP.get(attr_name, "basic")
                power_map = SPECIAL_ATTR_POWER_MAP if attr_type == 'special' else BASIC_ATTR_POWER_MAP
                threshold_power += power_map.get(max_level, 0)
        
        total_attr_power = TOTAL_ATTR_POWER_MAP.get(total_attr_value, 0)
        return threshold_power + total_attr_power, attr_breakdown
    
    def _preliminary_check(self, module_pool: List[ModuleInfo], prioritized_attrs: Optional[List[str]]) -> bool:
        if not prioritized_attrs: return True
        
        available_attrs = {part.name for module in module_pool for part in module.parts}
        prioritized_set = set(prioritized_attrs)
        
        intersection = available_attrs.intersection(prioritized_set)
        
        if len(intersection) < 2:
            self.logger.warning("="*50)
            self.logger.warning(">>> 前置检查失败：筛选无法进行！")
            self.logger.warning(f">>> 原因：在您选择的模组类型中，能找到的用户指定属性不足两种。")
            self.logger.warning(f">>> 找到的属性: {list(intersection)}")
            self.logger.warning(">>> 优化已自动跳过。请调整模组类型或筛选属性后重试。")
            self.logger.warning("="*50)
            return False
        return True

    def _calculate_optimization_score(self, modules: List[ModuleInfo], category: ModuleCategory, 
                                      prioritized_attrs: Optional[List[str]] = None) -> float:
        if not modules: return 0.0

        attr_breakdown = {}
        for module in modules:
            for part in module.parts:
                attr_breakdown[part.name] = attr_breakdown.get(part.name, 0) + part.value
        
        if prioritized_attrs:
            prioritized_set = set(prioritized_attrs)
            actual_attrs_set = set(attr_breakdown.keys())
            
            if not actual_attrs_set.issubset(prioritized_set): return 0.0
            if len(actual_attrs_set) < 2: return 0.0

        score = 0.0
        
        threshold_score = 0
        for attr_name, value in attr_breakdown.items():
            if value >= 20: threshold_score += 1000 + (value - 20) * 20
            elif value >= 16: threshold_score += 500 + (value - 16) * 15
            elif value >= 12: threshold_score += 100 + (value - 12) * 5
        score += threshold_score
        
        category_bonus = 0
        target_attrs = set()
        if category == ModuleCategory.ATTACK: target_attrs = ATTACK_ATTRIBUTES
        elif category == ModuleCategory.GUARDIAN: target_attrs = GUARDIAN_ATTRIBUTES
        elif category == ModuleCategory.SUPPORT: target_attrs = SUPPORT_ATTRIBUTES
        for attr_name, value in attr_breakdown.items():
            if attr_name in target_attrs:
                category_bonus += value * 5
        score += category_bonus

        physical_sum = sum(v for k, v in attr_breakdown.items() if k in PHYSICAL_ATTRIBUTES)
        magic_sum = sum(v for k, v in attr_breakdown.items() if k in MAGIC_ATTRIBUTES)
        if physical_sum > 0 and magic_sum > 0:
            score -= min(physical_sum, magic_sum) * 10
            
        score += sum(attr_breakdown.values()) * 0.1
        return score if score > 0 else 0.0

    def greedy_construct_solution(self, modules: List[ModuleInfo], category: ModuleCategory, prioritized_attrs: Optional[List[str]] = None) -> Optional[Tuple[List[ModuleInfo], float]]:
        if len(modules) < 4: return None
        current_modules = [random.choice(modules)]
        for _ in range(3):
            candidates = [(m, self._calculate_optimization_score(current_modules + [m], category, prioritized_attrs))
                          for m in modules if m not in current_modules]
            if not candidates: break
            
            valid_candidates = [c for c in candidates if c[1] > 0]
            if not valid_candidates: break
            
            if random.random() < 0.7:
                best_module = max(valid_candidates, key=lambda item: item[1])[0]
            else:
                top_candidates = sorted(valid_candidates, key=lambda item: item[1], reverse=True)[:5]
                best_module = random.choice(top_candidates)[0]
            current_modules.append(best_module)
            
        final_opt_score = self._calculate_optimization_score(current_modules, category, prioritized_attrs)
        return (current_modules, final_opt_score) if final_opt_score > 0 else None

    def local_search_improve(self, initial_modules: List[ModuleInfo], initial_opt_score: float, all_modules: List[ModuleInfo], category: ModuleCategory, prioritized_attrs: Optional[List[str]] = None) -> Tuple[List[ModuleInfo], float]:
        best_modules, best_opt_score = initial_modules, initial_opt_score
        for _ in range(self.local_search_iterations):
            improved_in_iter = False
            for i in range(len(best_modules)):
                current_best_module_for_swap, best_score_for_swap = None, best_opt_score
                sample_size = min(self.local_search_sample_size, len(all_modules))
                for new_module in random.sample(all_modules, sample_size):
                    if new_module in best_modules: continue
                    
                    new_modules = best_modules[:i] + [new_module] + best_modules[i+1:]
                    new_opt_score = self._calculate_optimization_score(new_modules, category, prioritized_attrs)
                    
                    if new_opt_score > best_score_for_swap:
                        best_score_for_swap = new_opt_score
                        current_best_module_for_swap = new_module
                        improved_in_iter = True
                
                if current_best_module_for_swap:
                    best_modules = best_modules[:i] + [current_best_module_for_swap] + best_modules[i+1:]
                    best_opt_score = best_score_for_swap

            if not improved_in_iter: break
        return best_modules, best_opt_score

    def optimize_modules(self, modules: List[ModuleInfo], category: ModuleCategory, top_n: int = 40, prioritized_attrs: Optional[List[str]] = None) -> List[ModuleSolution]:
        self.logger.info(f"开始优化 {category.value} 类型模组搭配")
        
        if category == ModuleCategory.All: module_pool = modules
        else: module_pool = [m for m in modules if self.get_module_category(m) == category]
            
        if not self._preliminary_check(module_pool, prioritized_attrs): return []
        
        self.logger.info(f"找到 {len(module_pool)} 个 {category.value} 类型模组用于组合")
        if len(module_pool) < 4:
            self.logger.warning(f"该类型模组数量不足4个，无法进行优化。")
            return []
        
        candidate_modules = self.prefilter_modules(module_pool)
        if len(candidate_modules) < 4:
            self.logger.warning(f"预筛选后模组数量不足4个，无法形成有效组合。")
            return []

        solutions, seen_combinations = [], set()
        max_attempts = int(self.max_solutions * 20) # 调整尝试次数
        for _ in range(max_attempts):
            if len(solutions) >= self.max_solutions: break

            # +++ 优化：多种子择优机制 +++
            # 1. 生成多个种子
            greedy_seeds = []
            for _ in range(self.num_greedy_seeds):
                seed = self.greedy_construct_solution(candidate_modules, category, prioritized_attrs)
                if seed:
                    greedy_seeds.append(seed)
            
            # 2. 如果没有找到任何有效种子，则跳过本次尝试
            if not greedy_seeds:
                continue

            # 3. 从多个种子中选出最优的一个作为起点
            initial_result = max(greedy_seeds, key=lambda item: item[1])
            
            # 4. 对这个高质量的起点进行精细的局部搜索
            improved_modules, improved_opt_score = self.local_search_improve(*initial_result, candidate_modules, category, prioritized_attrs)
            if improved_opt_score <= 0: continue

            module_ids = tuple(sorted([m.uuid for m in improved_modules]))
            if module_ids not in seen_combinations:
                seen_combinations.add(module_ids)
                final_combat_power, attr_breakdown = self.calculate_combat_power(improved_modules)
                solutions.append(ModuleSolution(improved_modules, final_combat_power, attr_breakdown, improved_opt_score))
        
        solutions.sort(key=lambda x: x.score, reverse=True)
        
        unique_solutions = {}
        for solution in solutions:
            attrs_ge_20 = tuple(sorted([name for name, value in solution.attr_breakdown.items() if value >= 20]))
            attrs_ge_16 = tuple(sorted([name for name, value in solution.attr_breakdown.items() if value >= 16]))
            signature = (attrs_ge_20, attrs_ge_16)

            if signature not in unique_solutions:
                unique_solutions[signature] = solution

        deduplicated_solutions = list(unique_solutions.values())
        self.logger.info(f"优化完成，找到 {len(solutions)} 个符合条件的解，去重后剩余 {len(deduplicated_solutions)} 个。")

        return deduplicated_solutions[:top_n]

    def print_solution_details(self, solution: ModuleSolution, rank: int):
        header = f"\n=== 第 {rank} 名搭配 (优化分: {solution.optimization_score:.2f}) ==="
        print(header); self._log_result(header)
        total_value_str = f"总属性值: {sum(solution.attr_breakdown.values())}"
        print(total_value_str); self._log_result(total_value_str)
        combat_power_str = f"战斗力: {solution.score}"
        print(combat_power_str); self._log_result(combat_power_str)
        print("\n模组列表:"); self._log_result("\n模组列表:")
        for i, module in enumerate(solution.modules, 1):
            parts_str = ", ".join([f"{p.name}+{p.value}" for p in module.parts])
            module_line = f"  {i}. {module.name} (品质{module.quality}) - {parts_str}"
            print(module_line); self._log_result(module_line)
        print("\n属性分布:"); self._log_result("\n属性分布:")
        for attr_name, value in sorted(solution.attr_breakdown.items()):
            attr_line = f"  {attr_name}: +{value}"
            print(attr_line); self._log_result(attr_line)

    def optimize_and_display(self, modules: List[ModuleInfo], category: ModuleCategory = ModuleCategory.All, 
                           top_n: int = 40, prioritized_attrs: Optional[List[str]] = None):
        separator = f"\n{'='*50}"
        print(separator); self._log_result(separator)
        title = f"模组搭配优化 - {category.value} 类型"
        print(title); self._log_result(title)
        print(separator); self._log_result(separator)
        
        optimal_solutions = self.optimize_modules(modules, category, top_n, prioritized_attrs)
        
        if not optimal_solutions:
            msg = f"未找到符合所有筛选条件的有效搭配。\n提示：请检查筛选属性是否过于苛刻，或模组池中缺少符合要求的模组。"
            print(msg); self._log_result(msg)
            return
        
        found_msg = f"\n找到 {len(optimal_solutions)} 个去重后的最优搭配 (将从末位开始显示，最优解在最后):"
        print(found_msg); self._log_result(found_msg)
        
        num_solutions = len(optimal_solutions)
        for i, solution in enumerate(reversed(optimal_solutions)):
            rank = num_solutions - i
            self.print_solution_details(solution, rank)
        
        print(separator); self._log_result(separator)
        print("统计信息:"); self._log_result("统计信息:")
        total_str = f"总模组数量: {len(modules)}"
        print(total_str); self._log_result(total_str)
        
        if category == ModuleCategory.All:
            category_count = len(modules)
        else:
            category_count = len([m for m in modules if self.get_module_category(m) == category])
        
        category_str = f"{category.value} 类型模组: {category_count}"
        print(category_str); self._log_result(category_str)
        
        if optimal_solutions:
            highest_score_str = f"最高战斗力: {optimal_solutions[0].score}"
            print(highest_score_str); self._log_result(highest_score_str)
        
        print(separator); self._log_result(separator)