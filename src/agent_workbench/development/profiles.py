"""Explicit provider settings, frozen per run rather than implicit defaults."""


def model_settings(grant):
    profile=grant.get('model_profile','fast')
    if profile not in ('fast','reasoned'):raise ValueError('unsupported development model profile')
    return {'profile':profile,'model':'deepseek-flash',
            'thinking':{'type':'enabled' if profile=='reasoned' else 'disabled'},
            'reasoning_effort':'high' if profile=='reasoned' else None,
            'timeout_seconds':180 if profile=='reasoned' else 90}
