# module_optimizer.py

import logging
import os
import random
import math
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor, as_completed

from logging_config import get_logger
from module_types import (
    ModuleInfo, ModuleType, ModuleAttrType, ModuleCategory,
    MODULE_CATEGORY_MAP, ATTR_THRESHOLDS, BASIC_ATTR_POWER_MAP, SPECIAL_ATTR_POWER_MAP,
    TOTAL_ATTR_POWER_MAP, BASIC_ATTR_IDS, SPECIAL_ATTR_IDS, ATTR_NAME_TYPE_MAP
)

# 获取日志记录器
logger = get_logger(__name__)

# --- 属性分类定义 (不变) ---
PHYSICAL_ATTRIBUTES = {"力量加持", "敏捷加持", "攻速专注"}
MAGIC_ATTRIBUTES = {"智力加持", "施法专注"}
ATTACK_ATTRIBUTES = {"特攻伤害", "精英打击", "力量加持", "敏捷加持", "智力加持"}
GUARDIAN_ATTRIBUTES = {"抵御魔法", "抵御物理"}
SUPPORT_ATTRIBUTES = {"特攻治疗加持", "专精治疗加持"}

# --- 解决方案的数据类 (不变) ---
@dataclass
class ModuleSolution:
    """代表一个模组搭配的解决方案。"""
    modules: List[ModuleInfo]
    attr_breakdown: Dict[str, int] = field(default_factory=dict)
    score: float = 0.0  # 最终战斗力
    optimization_score: float = 0.0 # 优化过程中使用的适应度分数

    def __post_init__(self):
        self.modules.sort(key=lambda m: m.uuid)

    def get_combination_id(self) -> Tuple[str, ...]:
        return tuple(m.uuid for m in self.modules)

# --- 顶层函数，用于并行执行 ---
# 这些函数定义在顶层，以便能被多进程模块 "pickle" 序列化。

def calculate_fitness(modules: List[ModuleInfo], category: ModuleCategory,
                      prioritized_attrs: Optional[List[str]] = None) -> float:
    """独立的适应度计算函数。"""
    if not modules or len(set(m.uuid for m in modules)) < 4: return 0.0
    attr_breakdown = {}
    for module in modules:
        for part in module.parts:
            attr_breakdown[part.name] = attr_breakdown.get(part.name, 0) + part.value
    
    score = 0.0
    if prioritized_attrs:
        prioritized_set = set(prioritized_attrs)
        actual_attrs_set = set(attr_breakdown.keys())
        match_count = len(prioritized_set.intersection(actual_attrs_set))
        score += match_count * 100
        mismatch_count = len(actual_attrs_set.difference(prioritized_set))
        score -= mismatch_count * 50

    threshold_score = 0
    for attr_name, value in attr_breakdown.items():
        if value >= 20: threshold_score += 1000 + (value - 20) * 20
        elif value >= 16: threshold_score += 500 + (value - 16) * 15
        elif value >= 12: threshold_score += 100 + (value - 12) * 5
    score += threshold_score

    target_attrs = set()
    if category == ModuleCategory.ATTACK: target_attrs = ATTACK_ATTRIBUTES
    elif category == ModuleCategory.GUARDIAN: target_attrs = GUARDIAN_ATTRIBUTES
    elif category == ModuleCategory.SUPPORT: target_attrs = SUPPORT_ATTRIBUTES
    score += sum(value * 5 for attr_name, value in attr_breakdown.items() if attr_name in target_attrs)

    physical_sum = sum(v for k, v in attr_breakdown.items() if k in PHYSICAL_ATTRIBUTES)
    magic_sum = sum(v for k, v in attr_breakdown.items() if k in MAGIC_ATTRIBUTES)
    if physical_sum > 0 and magic_sum > 0:
        score -= min(physical_sum, magic_sum) * 10

    score += sum(attr_breakdown.values()) * 0.1
    return max(0.0, score)

def run_single_ga_campaign(
    modules: List[ModuleInfo],
    category: ModuleCategory,
    prioritized_attrs: Optional[List[str]],
    ga_params: Dict
) -> List[ModuleSolution]:
    """
    执行一次完整的遗传算法流程。这是单个进程工作单元的目标函数。
    """
    # 辅助函数嵌套在这里，不需要被序列化
    def _initialize_population(pool, size):
        population, seen = [], set()
        if len(pool) < 4: return []
        try:
            max_possible_combinations = math.comb(len(pool), 4)
        except AttributeError:
            def combinations(n, k):
                if k < 0 or k > n: return 0
                if k == 0 or k == n: return 1
                if k > n // 2: k = n - k
                res = 1
                for i in range(k):
                    res = res * (n - i) // (i + 1)
                return res
            max_possible_combinations = combinations(len(pool), 4)
        target_size = min(size, max_possible_combinations)
        if target_size == 0: return []
        while len(population) < target_size:
            selected_modules = random.sample(pool, 4)
            solution = ModuleSolution(modules=selected_modules)
            combo_id = solution.get_combination_id()
            if combo_id not in seen:
                solution.optimization_score = calculate_fitness(solution.modules, category, prioritized_attrs)
                population.append(solution)
                seen.add(combo_id)
        return population
 
    def _selection(population):
        tournament = random.sample(population, ga_params['tournament_size'])
        return max(tournament, key=lambda s: s.optimization_score)

    def _crossover(p1, p2):
        if random.random() > ga_params['crossover_rate']: return deepcopy(p1), deepcopy(p2)
        child1_mods = p1.modules[:2] + [m for m in p2.modules if m.uuid not in {mod.uuid for mod in p1.modules[:2]}][:2]
        child2_mods = p2.modules[:2] + [m for m in p1.modules if m.uuid not in {mod.uuid for mod in p2.modules[:2]}][:2]
        return (ModuleSolution(modules=child1_mods) if len(child1_mods) == 4 else deepcopy(p1),
                ModuleSolution(modules=child2_mods) if len(child2_mods) == 4 else deepcopy(p2))

    def _mutate(solution, pool):
        if random.random() > ga_params['mutation_rate']: return
        current_ids = {m.uuid for m in solution.modules}
        candidates = [m for m in pool if m.uuid not in current_ids]
        if not candidates: return
        index_to_replace = random.randrange(len(solution.modules))
        solution.modules[index_to_replace] = random.choice(candidates)
        solution.modules.sort(key=lambda m: m.uuid)

    def _local_search(solution, pool):
        best_solution = deepcopy(solution)
        while True:
            improved = False
            for i in range(len(best_solution.modules)):
                current_module = best_solution.modules[i]
                best_replacement = None
                best_new_score = best_solution.optimization_score
                for new_module in pool:
                    if new_module.uuid in {m.uuid for m in best_solution.modules if m.uuid != current_module.uuid}: continue
                    temp_modules = best_solution.modules[:i] + [new_module] + best_solution.modules[i+1:]
                    new_score = calculate_fitness(temp_modules, category, prioritized_attrs)
                    if new_score > best_new_score:
                        best_new_score = new_score
                        best_replacement = new_module
                if best_replacement:
                    best_solution.modules[i] = best_replacement
                    best_solution.optimization_score = best_new_score
                    best_solution.modules.sort(key=lambda m: m.uuid)
                    improved = True
            if not improved: break
        return best_solution
    
    population = _initialize_population(modules, ga_params['population_size'])
    if not population: return []
    for _ in range(ga_params['generations']):
        population.sort(key=lambda s: s.optimization_score, reverse=True)
        next_gen, elite_count = [], int(ga_params['population_size'] * ga_params['elitism_rate'])
        next_gen.extend(deepcopy(population[:elite_count]))
        while len(next_gen) < ga_params['population_size']:
            p1, p2 = _selection(population), _selection(population)
            c1, c2 = _crossover(p1, p2)
            _mutate(c1, modules); _mutate(c2, modules)
            next_gen.extend([c1, c2])
        for individual in next_gen:
            individual.optimization_score = calculate_fitness(individual.modules, category, prioritized_attrs)
        next_gen.sort(key=lambda s: s.optimization_score, reverse=True)
        local_search_count = int(ga_params['population_size'] * ga_params['local_search_rate'])
        for i in range(local_search_count):
            next_gen[i] = _local_search(next_gen[i], modules)
        population = next_gen
    return sorted(population, key=lambda s: s.optimization_score, reverse=True)


class ModuleOptimizer:
    """
    使用并行的多轮遗传算法来寻找最优模组组合。
    """

    def __init__(self):
        self.logger = logger
        self._result_log_file = None
        self.ga_params = {
            'population_size': 100, 'generations': 40, 'mutation_rate': 0.1,
            'crossover_rate': 0.8, 'elitism_rate': 0.1, 'tournament_size': 5,
            'local_search_rate': 0.3,
        }
        self.num_campaigns = max(1, os.cpu_count() - 1)
        self.quality_threshold = 12
        self.prefilter_top_n_per_attr = 30
        self.prefilter_top_n_total_value = 50

    def _get_current_log_file(self) -> Optional[str]:
        try:
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, logging.FileHandler): return handler.baseFilename
            return None
        except Exception as e:
            self.logger.warning(f"无法获取日志文件路径: {e}")
            return None

    def _log_result(self, message: str):
        try:
            if self._result_log_file is None: self._result_log_file = self._get_current_log_file()
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
        candidate_modules, attr_modules = set(), {p.name: [] for m in modules for p in m.parts}
        for module in modules:
            for part in module.parts: attr_modules[part.name].append((module, part.value))
        for attr_name, module_values in attr_modules.items():
            sorted_by_attr = sorted(module_values, key=lambda x: x[1], reverse=True)
            candidate_modules.update(item[0] for item in sorted_by_attr[:self.prefilter_top_n_per_attr])
        sorted_by_total_value = sorted(modules, key=lambda m: sum(p.value for p in m.parts), reverse=True)
        candidate_modules.update(sorted_by_total_value[:self.prefilter_top_n_total_value])
        filtered_modules = list(candidate_modules)
        self.logger.info(f"预筛选完成，候选池数量: {len(filtered_modules)}")
        return filtered_modules

    # --- CORRECTED METHOD ---
    def calculate_combat_power(self, modules: List[ModuleInfo]) -> Tuple[int, Dict[str, int]]:
        """
        修正后的战斗力计算方法。
        """
        attr_breakdown = {}
        # 先初始化字典，再遍历模组进行累加
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
    # --- END OF CORRECTION ---

    def _preliminary_check(self, module_pool: List[ModuleInfo], prioritized_attrs: Optional[List[str]]) -> bool:
        if not prioritized_attrs: return True
        available_attrs = {p.name for m in module_pool for p in m.parts}
        prioritized_set = set(prioritized_attrs)
        intersection = available_attrs.intersection(prioritized_set)
        if len(intersection) < 2:
            self.logger.warning("="*50 + "\n>>> 前置检查失败：筛选无法进行！\n" +
                                f">>> 原因：在您选择的模组类型中，能找到的用户指定属性不足两种。\n" +
                                f">>> 找到的属性: {list(intersection)}\n" +
                                ">>> 优化已自动跳过。请调整模组类型或筛选属性后重试。\n" + "="*50)
            return False
        return True

    def _get_attribute_level_key(self, attr_breakdown: Dict[str, int]) -> Tuple[str, ...]:
        """根据属性分布计算出一个用于去重的唯一键（基于属性等级）。"""
        levels = []
        for attr_name, value in sorted(attr_breakdown.items()):
            level_str = "（等级0）"
            if value >= 20: level_str = "（等级6）"
            elif value >= 16: level_str = "（等级5）"
            elif value >= 12: level_str = "（等级4）"
            elif value >= 8: level_str = "（等级3）"
            elif value >= 4: level_str = "（等级2）"
            elif value >= 1: level_str = "（等级1）"
            levels.append(f"{attr_name}{level_str}")
        return tuple(levels)

    def optimize_modules(self, modules: List[ModuleInfo], category: ModuleCategory, top_n: int = 40,
                         prioritized_attrs: Optional[List[str]] = None,
                         progress_callback: Optional[Callable[[str], None]] = None) -> List[ModuleSolution]:
        
        self.logger.info(f"开始为 {category.value} 类型模组进行优化 (使用 {self.num_campaigns} 个并行任务)")
        module_pool = modules if category == ModuleCategory.All else [m for m in modules if self.get_module_category(m) == category]
        
        if prioritized_attrs:
            self.logger.info(f"应用严格筛选: 只保留全部属性都在 {prioritized_attrs} 列表中的模组。")
            original_count = len(module_pool)
            prioritized_set = set(prioritized_attrs)
            module_pool = [m for m in module_pool if all(p.name in prioritized_set for p in m.parts)]
            self.logger.info(f"严格筛选完成: 模组数量从 {original_count} 个减少到 {len(module_pool)} 个。")

        if not self._preliminary_check(module_pool, prioritized_attrs): return []
        candidate_modules = self.prefilter_modules(module_pool)
        if len(candidate_modules) < 4:
            self.logger.warning("预筛选后模组数量不足4个，无法形成有效组合。")
            return []

        high_quality_modules = [m for m in candidate_modules if sum(p.value for p in m.parts) >= self.quality_threshold]
        low_quality_modules = [m for m in candidate_modules if sum(p.value for p in m.parts) < self.quality_threshold]
        self.logger.info(f"模组分池完成：高品质模组 {len(high_quality_modules)} 个，低品质模组 {len(low_quality_modules)} 个。")
        if len(high_quality_modules) < 4:
            self.logger.warning("高品质模组数量不足4个，将使用全部候选模组进行优化。")
            high_quality_modules = candidate_modules
            low_quality_modules = []

        all_best_solutions = []
        with ProcessPoolExecutor(max_workers=self.num_campaigns) as executor:
            self.logger.info(f"--- 第一阶段：在高品质模组池上并行运行 {self.num_campaigns} 轮GA ---")
            if progress_callback: progress_callback(f"正在运行 {self.num_campaigns} 个并行优化任务...")
            futures = [executor.submit(run_single_ga_campaign, high_quality_modules, category, prioritized_attrs, self.ga_params)
                       for _ in range(self.num_campaigns)]
            for i, future in enumerate(as_completed(futures)):
                try:
                    campaign_results = future.result()
                    if campaign_results:
                        all_best_solutions.extend(campaign_results)
                        best_score = campaign_results[0].optimization_score
                        self.logger.info(f"任务 {i+1}/{self.num_campaigns} 完成。最高适应度: {best_score:.2f}")
                        if progress_callback: progress_callback(f"任务 {i+1}/{self.num_campaigns} 完成. 最高分: {best_score:.2f}")
                except Exception as e:
                    self.logger.error(f"一个优化任务失败: {e}")

        self.logger.info("--- 第二阶段：使用低品质模组对最优解集进行精细微调 ---")
        if progress_callback: progress_callback("第二阶段：精细微调顶尖结果...")
        unique_solutions = list({sol.get_combination_id(): sol for sol in all_best_solutions}.values())
        unique_solutions.sort(key=lambda s: s.optimization_score, reverse=True)
        
        refined_solutions = []
        if not low_quality_modules:
            self.logger.info("低品质模组池为空，跳过微调阶段。")
            refined_solutions = unique_solutions
        else:
            solutions_to_refine = unique_solutions[:30]
            for solution in solutions_to_refine:
                best_refined_solution = self._local_search_improvement(solution, candidate_modules, category, prioritized_attrs)
                if best_refined_solution.optimization_score > solution.optimization_score:
                     self.logger.info(f"解通过微调得到提升！分数: {solution.optimization_score:.2f} -> {best_refined_solution.optimization_score:.2f}")
                refined_solutions.append(best_refined_solution)
        
        final_results = unique_solutions + refined_solutions
        for solution in final_results:
            if not solution.attr_breakdown:
                solution.score, solution.attr_breakdown = self.calculate_combat_power(solution.modules)

        final_results.sort(key=lambda s: s.optimization_score, reverse=True)
        
        solutions_by_attr_level = {}
        for solution in final_results:
            attr_level_key = self._get_attribute_level_key(solution.attr_breakdown)
            if attr_level_key not in solutions_by_attr_level:
                solutions_by_attr_level[attr_level_key] = solution

        deduplicated_solutions = list(solutions_by_attr_level.values())
        deduplicated_solutions.sort(key=lambda s: s.score, reverse=True)

        self.logger.info(f"并行优化完成。共找到 {len(deduplicated_solutions)} 个基于属性等级去重的优质组合。")
        if progress_callback: progress_callback(f"完成！共找到 {len(deduplicated_solutions)} 个独特组合。")

        return deduplicated_solutions[:top_n]
    
    def _local_search_improvement(self, solution: ModuleSolution, module_pool: List[ModuleInfo], category: ModuleCategory, prioritized_attrs: Optional[List[str]]) -> ModuleSolution:
        best_solution = deepcopy(solution)
        best_solution.optimization_score = calculate_fitness(best_solution.modules, category, prioritized_attrs)
        while True:
            improved = False
            for i in range(len(best_solution.modules)):
                for new_module in module_pool:
                    if new_module.uuid in {m.uuid for m in best_solution.modules}: continue
                    temp_modules = best_solution.modules[:i] + [new_module] + best_solution.modules[i+1:]
                    new_score = calculate_fitness(temp_modules, category, prioritized_attrs)
                    if new_score > best_solution.optimization_score:
                        best_solution.modules = temp_modules
                        best_solution.optimization_score = new_score
                        best_solution.modules.sort(key=lambda m: m.uuid)
                        improved = True
                        break 
                if improved: break
            if not improved: break
        return best_solution
        
    def print_solution_details(self, solution: ModuleSolution, rank: int):
        header = f"\n=== 第 {rank} 名搭配 (适应分: {solution.optimization_score:.2f}) ==="
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
            orname="（等级0）"
            if value >= 20: orname = "（等级6）"
            elif value >= 16: orname = "（等级5）"
            elif value >= 12: orname = "（等级4）"
            elif value >= 8: orname = "（等级3）"
            elif value >= 4: orname = "（等级2）"
            elif value >= 1: orname = "（等级1）"
            attr_line = f"  {attr_name}{orname}: +{value}"
            print(attr_line); self._log_result(attr_line)

    def optimize_and_display(self, modules: List[ModuleInfo], category: ModuleCategory = ModuleCategory.All,
                           top_n: int = 40, prioritized_attrs: Optional[List[str]] = None,
                           progress_callback: Optional[Callable[[str], None]] = None):
        separator = f"\n{'='*50}"
        print(separator); self._log_result(separator)
        title = f"模组搭配优化 - {category.value} 类型"
        print(title); self._log_result(title)
        print(separator); self._log_result(separator)
        
        optimal_solutions = self.optimize_modules(modules, category, top_n, prioritized_attrs, progress_callback)
        
        if not optimal_solutions:
            msg = f"未找到符合所有筛选条件的有效搭配。\n提示：请检查筛选属性是否过于苛刻，或模组池中缺少符合要求的模组。"
            print(msg); self._log_result(msg)
            return
        
        found_msg = f"\n找到 {len(optimal_solutions)} 个基于属性等级去重后的最优搭配 (将从末位开始显示，最优解在最后):"
        print(found_msg); self._log_result(found_msg)
        
        num_solutions = len(optimal_solutions)
        for i, solution in enumerate(reversed(optimal_solutions)):
            rank = num_solutions - i
            self.print_solution_details(solution, rank)
        
        print(separator); self._log_result(separator)