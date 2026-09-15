def analysis():
    return {
        "functionalOverview": {
            "purpose": "登录",
            "applicableObjects": [],
            "actors": [],
            "entryPoints": [],
            "explicitExclusions": [],
        },
        "scenarioFactors": [],
        "businessRules": [],
        "scenarioBreakdown": [],
        "openQuestions": [],
    }


def case(title="验证登录", module="登录"):
    return {
        "case_module": module,
        "case_title": title,
        "case_type": "功能测试",
        "priority": "2",
        "precondition": [],
        "test_steps": ["1. 登录"],
        "expected_results": ["1. 展示首页"],
    }


def points():
    return {
        "categories": [
            {
                "model": "登录",
                "data": [
                    {
                        "test_model": "功能场景",
                        "test_points": [{"case_name": "验证登录"}],
                    }
                ],
            }
        ]
    }
