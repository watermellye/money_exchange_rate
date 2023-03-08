import asyncio
import json
from hoshino import aiorequests
from pathlib import Path
from datetime import datetime

current_dir = Path(__file__).parent.absolute()
data_dir = current_dir / "data"

data_dir.mkdir(exist_ok=True)

url_prefix = "https://open.er-api.com/v6/"


def getNowtime() -> int:
    return int(datetime.now().timestamp())


async def queryHuilv(code1: str, code2: str, num: float) -> float:
    '''
    num个code1可以转为多少个code2
    '''
    code1 = code1.upper()
    code2 = code2.upper()

    cache_path = data_dir / f'{code1}.json'
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as fp:
            try:
                cache = json.load(fp)
            except Exception as e:
                pass
            else:
                if ("rates" in cache) and (getNowtime() - cache.get("time", 0) < 24 * 3600):  # 缓存有效
                    if (code2 not in cache["rates"]):
                        raise Exception(f'无法识别的货币代码：{code2}')
                    return num * cache["rates"][code2]

    url = f'{url_prefix}latest/{code1}'

    try:
        resp = await aiorequests.get(url)
    except Exception as e:
        raise Exception(f'向服务器请求汇率失败：{e}')

    assert resp.status_code == 200, f'url [{url}] request fail: code={resp.status_code}'
    res = await resp.json()
    #print(json.dumps(res_data, ensure_ascii=False, indent=4))

    if res.get("result", "error") != "success":
        raise Exception(f'获取汇率结果失败：{res.get("error-type", res)}')

    assert "time_last_update_unix" in res, f'"time_last_update_unix" not found in request return'
    assert "rates" in res, f'"rates" not found in request return'

    with open(cache_path, "w", encoding="utf-8") as fp:
        json.dump({"time": res["time_last_update_unix"], "rates": res["rates"]}, fp, ensure_ascii=False, indent=4)

    if (code2 not in res["rates"]):
        raise Exception(f'无法识别的货币代码：{code2}')
    return num * res["rates"][code2]


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    print(loop.run_until_complete(queryHuilv("USD", "CNY", 100)))
