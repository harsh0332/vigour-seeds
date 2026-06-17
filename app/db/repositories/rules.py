import asyncio
from typing import Optional, List
from app.db.client import supabase_client
from app.models.db_models import RecommendationRuleRow
from app.core.logging import logger

class RulesRepository:
    @staticmethod
    def _match(crop: str, crop_stage: str, problem_category: str, irrigation_type: str, region: str) -> Optional[RecommendationRuleRow]:
        if not supabase_client:
            return None

        # Fetch all rules
        res = supabase_client.table("recommendation_rules").select("*").execute()
        if not res.data:
            return None

        rules = [RecommendationRuleRow(**r) for r in res.data]
        matched_rules = []

        # Canonicalize input problem
        norm_problem = (problem_category or "").strip().lower()
        if norm_problem in ["none", ""]:
            norm_problem = "-"

        for r in rules:
            # 1. Match Crop
            rule_crop = r.crop.strip().lower()
            if rule_crop != "any" and rule_crop != crop.strip().lower():
                continue

            # 2. Match Stage
            rule_stage = r.crop_stage.strip().lower()
            if rule_stage != "any" and rule_stage != crop_stage.strip().lower():
                continue

            # 3. Match Problem Category
            rule_prob = r.problem_category.strip().lower()
            if rule_prob != "any":
                if rule_prob == "-" or rule_prob == "none":
                    if norm_problem != "-":
                        continue
                elif rule_prob != norm_problem:
                    continue

            # 4. Match Irrigation Type
            rule_irr = r.irrigation_type.strip().lower()
            if rule_irr not in ["any", "*"]:
                inp_irr = irrigation_type.strip().lower()
                if rule_irr == "rainfed/irrigated":
                    if inp_irr not in ["rainfed", "irrigated", "rainfed/irrigated", "any", "*"]:
                        continue
                elif rule_irr != inp_irr:
                    continue

            # 5. Match Region
            rule_reg = r.region.strip().lower()
            if rule_reg not in ["any", "*"]:
                inp_reg = region.strip().lower()
                regions_list = [reg.strip() for reg in rule_reg.split(",")]
                if inp_reg not in regions_list:
                    continue

            # Compute match specificity score
            score = 0
            if rule_crop != "any":
                score += 10
            if rule_stage != "any":
                score += 5
            if rule_prob != "any":
                score += 5
            if rule_irr not in ["any", "*"]:
                score += 2
            if rule_reg not in ["any", "*"]:
                score += 2

            matched_rules.append((score, r))

        if not matched_rules:
            return None

        # Sort by score descending
        matched_rules.sort(key=lambda x: x[0], reverse=True)
        return matched_rules[0][1]

    async def match(self, crop: str, crop_stage: str, problem_category: str, irrigation_type: str, region: str) -> Optional[RecommendationRuleRow]:
        return await asyncio.to_thread(self._match, crop, crop_stage, problem_category, irrigation_type, region)

rules_repo = RulesRepository()
