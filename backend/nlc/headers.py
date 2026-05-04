import random


def generate_user_agents(num_agents: int = 20) -> list:
    user_agents = []
    for _ in range(num_agents):
        user_agent = (
            f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
            f'Chrome/{random.randint(1, 200)}.0.0.0 Safari/537.36 Edg/{random.randint(1, 200)}.0.0.0'
        )
        user_agents.append(user_agent)
    return user_agents


_user_agents = generate_user_agents(20)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}

NLC_SEARCH_URL = "http://opac.nlc.cn/F"
NLC_DETAIL_URL = "http://opac.nlc.cn/F/"


def get_shukui_headers() -> dict:
    return {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8, '
                  'application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Host': 'www.shukui.net',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': random.choice(_user_agents),
        'Referer': 'https://www.shukui.net/',
    }

