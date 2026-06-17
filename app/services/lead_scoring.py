from typing import Any, Dict

class LeadScoringService:
    @staticmethod
    def score(lead: Any) -> Dict[str, Any]:
        """
        Deterministic, points-based lead scoring for new distributors.
        
        monthly_sales_volume_inr: >=1,000,000 -> 40 ; 500k–999k -> 30 ; 200k–499k -> 20 ; <200k -> 10
        years_in_agri_business:   >=10 -> 20 ; 5–9 -> 15 ; 2–4 -> 10 ; <2 -> 5
        warehouse_available:      TRUE -> 15 (+5 if warehouse_size_sqft>=1000) ; FALSE -> 0
        current_brands_sold:      >=3 brands -> 15 ; 1–2 -> 10 ; 0 -> 5
        staff_size:               >=4 -> 10 ; 2–3 -> 7 ; 1 -> 3 ; <1 -> 0
        area_covered_radius_km:   >=25 -> 10 ; 10–24 -> 6 ; <10 -> 3
        
        TOTAL out of ~110.
        HOT  >= 70
        WARM 45–69
        COLD < 45
        """
        def get_val(field: str, default: Any = None) -> Any:
            if isinstance(lead, dict):
                return lead.get(field, default)
            return getattr(lead, field, default)

        breakdown = {}
        
        # 1. monthly_sales_volume_inr
        sales = get_val("monthly_sales_volume_inr")
        if sales is None:
            sales_pts = 10
        elif sales >= 1000000:
            sales_pts = 40
        elif sales >= 500000:
            sales_pts = 30
        elif sales >= 200000:
            sales_pts = 20
        else:
            sales_pts = 10
        breakdown["monthly_sales_volume_inr"] = sales_pts

        # 2. years_in_agri_business
        years = get_val("years_in_agri_business")
        if years is None:
            years_pts = 5
        elif years >= 10:
            years_pts = 20
        elif years >= 5:
            years_pts = 15
        elif years >= 2:
            years_pts = 10
        else:
            years_pts = 5
        breakdown["years_in_agri_business"] = years_pts

        # 3. warehouse_available
        wh_avail = get_val("warehouse_available")
        wh_size = get_val("warehouse_size_sqft")
        wh_pts = 0
        if wh_avail is True or str(wh_avail).lower() in ["true", "y", "yes", "हाँ", "हा"]:
            wh_pts = 15
            if wh_size is not None:
                try:
                    wh_size_val = float(wh_size)
                    if wh_size_val >= 1000:
                        wh_pts += 5
                except (ValueError, TypeError):
                    pass
        breakdown["warehouse_available"] = wh_pts

        # 4. current_brands_sold
        brands = get_val("current_brands_sold")
        brands_list = []
        if brands:
            if isinstance(brands, str):
                parts = [b.strip() for b in brands.split(",") if b.strip()]
                for p in parts:
                    if p.lower() not in ["none", "कोई नहीं", "nhi", "no", "nil", ""]:
                        brands_list.append(p)
            elif isinstance(brands, list):
                for b in brands:
                    if str(b).strip().lower() not in ["none", "कोई नहीं", "nhi", "no", "nil", ""]:
                        brands_list.append(b)
        
        num_brands = len(brands_list)
        if num_brands >= 3:
            brands_pts = 15
        elif num_brands >= 1:
            brands_pts = 10
        else:
            brands_pts = 5
        breakdown["current_brands_sold"] = brands_pts

        # 5. staff_size
        staff = get_val("staff_size")
        if staff is None:
            staff_pts = 0
        else:
            try:
                staff_val = int(staff)
                if staff_val >= 4:
                    staff_pts = 10
                elif staff_val >= 2:
                    staff_pts = 7
                elif staff_val >= 1:
                    staff_pts = 3
                else:
                    staff_pts = 0
            except (ValueError, TypeError):
                staff_pts = 0
        breakdown["staff_size"] = staff_pts

        # 6. area_covered_radius_km
        radius = get_val("area_covered_radius_km")
        if radius is None:
            radius_pts = 3
        else:
            try:
                radius_val = float(radius)
                if radius_val >= 25:
                    radius_pts = 10
                elif radius_val >= 10:
                    radius_pts = 6
                else:
                    radius_pts = 3
            except (ValueError, TypeError):
                radius_pts = 3
        breakdown["area_covered_radius_km"] = radius_pts

        # Total points calculation
        total_score = sum(breakdown.values())
        
        # Classification band
        if total_score >= 70:
            band = "HOT"
        elif total_score >= 45:
            band = "WARM"
        else:
            band = "COLD"
            
        try:
            from app.services.metrics import metrics_service
            metrics_service.record_distributor_score(band)
        except Exception:
            pass
            
        return {
            "score": total_score,
            "band": band,
            "breakdown": breakdown
        }

lead_scoring = LeadScoringService()
