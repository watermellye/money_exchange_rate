import json
from hoshino import Service, priv
from hoshino.util import FreqLimiter, normalize_str
from pathlib import Path

import re
from .checkdata import queryHuilv
from traceback import print_exc
from fuzzywuzzy import process
from hoshino.typing import CQEvent, HoshinoBot
from enum import IntEnum, unique

flmt = FreqLimiter(1)

sv = Service('汇率')
help_msg = '''
汇率功能指令表：（请替换尖括号及其内部的内容）
<货币>汇率
<货币1> <货币2>汇率
<数字><货币1>可以换多少<货币2> 
汇率定义 <数字><新币种> <数字><已有币种>
取消汇率定义 <已有货币>
'''.strip()


@sv.on_fullmatch(('汇率', '汇率帮助'))
async def huilvHelp(bot, ev, errorMsg=""):
    await bot.send(ev, f'{errorMsg}\n{help_msg}'.strip())

curpath = Path(__file__).parent.absolute()

code_path = curpath / 'code.json'
assert code_path.exists(), "货币标准识别码文件不存在！"
with open(code_path, "r", encoding='utf-8') as fp:
    code_dict = json.load(fp)


def loadConfig() -> dict:  # 加载config
    with open(userdefine_data_path, "r", encoding='utf-8') as fp:
        return json.load(fp)


def saveConfig(config:dict) -> None:
    with open(userdefine_data_path, "w", encoding='utf-8') as fp:
        json.dump(config, fp, ensure_ascii=False, indent=4)

        
userdefine_data_path = curpath / '汇率定义.json'
if not userdefine_data_path.exists():
    saveConfig({})

    
def doReplace(num: float, money1: str, money2: str):
    config = loadConfig()

    def doReplaceMoney(money: str) -> str:
        return config[money][1] if money in config else money

    num *= ((config.get(money1, [1]))[0])
    num /= ((config.get(money2, [1]))[0])
    return num, doReplaceMoney(money1), doReplaceMoney(money2)


def money2code(money: str, money_original: str, msg: list) -> str:
    code = ""
    money_str = f'{money}' + (f'(转换自{money_original})' if money != money_original else "")
    if money in code_dict:
        code = code_dict[money]
    else:
        guess_name, score = process.extractOne(normalize_str(money), list(code_dict), processor=normalize_str)
        if score == 100:
            code = code_dict[guess_name]
        elif score < 50:
            raise
        else:
            msg.append(f'无法识别{money_str}；您有{score}%可能说的是{guess_name}({code_dict[guess_name]})')
    return code.upper()


async def getHuilvData(money1_original: str, num_original: float = 100, money2_original: str = "人民币"):
    money1_original = money1_original.upper()
    money2_original = money2_original.upper()
    num, money1, money2 = doReplace(num_original, money1_original, money2_original)  # 等效金额

    msg = []
    code1 = money2code(money1, money1_original, msg)
    code2 = money2code(money2, money2_original, msg)
    if len(msg):
        return '\n'.join(msg)

    try:
        num_exchange = await queryHuilv(code1, code2, num)
    except Exception as e:
        print_exc()
        return f'查询汇率失败：{e}'

    return f'{num_original}{money1_original}{("(" + code1 + ")") if money1_original == money1 and money1 != code1 else ""}可以兑换{num_exchange}{money2_original}{("(" + code2 + ")") if money2_original == money2 and money2 != code2 else ""}'


@sv.on_suffix("汇率")
async def huilvSimple(bot, ev):
    '''
    美元 汇率
    美元 欧元汇率
    123 美元 汇率
    '''
    # 冷却器检查
    if not flmt.check(ev['user_id']):
        await bot.send(ev, f"查询冷却中，请{flmt.left_time(ev['user_id']):.2f}秒后再试~", at_sender=True)
        return
    money = ev.raw_message.replace("汇率", "").strip().split()
    if len(money) == 1:
        m1 = money[0]
        m2 = "人民币"
    elif len(money) == 2:
        m1 = money[0]
        m2 = money[1]
    else:
        await huilvHelp(bot, ev, f'接受1~2个参数，您输入了{len(money)}个参数：{money}')
        return

    flmt.start_cd(ev['user_id'])

    try:
        float(m1)
    except:
        s1 = await getHuilvData(m1, 100, m2)
        s2 = "" if ("无法识别" in s1 or "失败" in s1) else await getHuilvData(m2, 100, m1)
        outp = f'{s1}\n{s2}'
    else:
        outp = await getHuilvData(m2, float(m1))
    await bot.send(ev, f'{outp.strip()}\nRates By Exchange Rate API')


@sv.on_rex(r'((?P<num>\d+(?:\.\d+)?)|(?:.*))(?P<keyword>.*?)[可][以](兑换|[换])[多][少](?P<keyword2>.*?)$')
async def huilvHard(bot, ev):
    # 冷却器检查
    if not flmt.check(ev['user_id']):
        await bot.send(ev, f"查询冷却中，请{flmt.left_time(ev['user_id']):.2f}秒后再试~", at_sender=True)
        return
    money = ev['match'].group('keyword')
    money2 = ev['match'].group('keyword2')
    num = float(ev['match'].group('num'))
    msg = await getHuilvData(money, num, money2)
    flmt.start_cd(ev['user_id'])
    await bot.send(ev, f'{msg.strip()}\nRates By Exchange Rate API')


@unique
class MoneyType(IntEnum):
    Undefined = 0
    Userdefined = 1
    Predefined = 2


class Money:
    def __init__(self, num: float, name: str):
        assert num > 0, f'不可接受的数字：{num}'
        self.Num = num
        self.Name = name


    @property
    def Type(self) -> MoneyType:
        if self.Name in code_dict:
            return MoneyType.Predefined
        guess_name, score = process.extractOne(normalize_str(self.Name), list(code_dict), processor=normalize_str)
        if score == 100:
            return MoneyType.Predefined
        config = loadConfig()
        return MoneyType.Userdefined if self.Name in config else MoneyType.Undefined

    @property
    def Code(self) -> str:
        if self.Name in code_dict:
            return code_dict[self.Name]
        guess_name, score = process.extractOne(normalize_str(self.Name), list(code_dict), processor=normalize_str)
        if score == 100:
            return code_dict[guess_name]
        return ""

@sv.on_prefix('汇率定义', '汇率设置')
async def huilvDefine(bot: HoshinoBot, ev: CQEvent):
    msg: str = ev.message.extract_plain_text().strip()
    text_list = [y for x in re.split(r'(\d+(?:\.\d+)?)', msg) if len(y := x.strip())]
    try:
        x = Money(float(text_list[0]), text_list[1].upper())
        y = Money(float(text_list[2]), text_list[3].upper())
    except Exception as e:
        await bot.finish(ev, "识别失败\n格式应为：汇率定义 <数字><新币种> <数字><已有币种>")

    if x.Type == y.Type == MoneyType.Undefined:
        await bot.finish(ev, f'汇率定义失败：[{x.Name}]和[{y.Name}]均未定义')
    if x.Type == y.Type == MoneyType.Userdefined:
        await bot.finish(ev, f'汇率定义失败：[{x.Name}]和[{y.Name}]均为用户定义货币\n为避免混淆，请先使用“取消定义汇率”删除你想修改的货币，再重新发送本指令')
    if x.Type == y.Type == MoneyType.Predefined:
        await bot.finish(ev, f'汇率定义失败：[{x.Name}]和[{y.Name}]均为预定义货币')

    config = loadConfig()
    
    if x.Type > y.Type:
        x, y = y, x
    y.Num /= x.Num
    x.Num = 1
    
    outp = []
    if x.Type == MoneyType.Undefined:
        if y.Type == MoneyType.Userdefined:
            y.Num *= config[y.Name][0]
            y.Name = config[y.Name][1]
    else:  # x.Type == MoneyType.Userdefined and y.Type == MoneyType.Predefined:
        outp.append(f'原有定义：1{x.Name}={config[x.Name][0]}{config[x.Name][1]}')

    config[x.Name] = [y.Num, y.Code]
    saveConfig(config)
    outp.append(f'设置成功：1{x.Name}={y.Num}{y.Code}')
    await bot.send(ev, "\n".join(outp).strip())


@sv.on_prefix(('取消定义汇率', '取消汇率定义'))
async def huilvDelete(bot, ev):
    msg: str = ev.message.extract_plain_text().strip()
    config = loadConfig()
    if msg not in config:
        await bot.finish(ev, f'没有找到[{msg}]的定义')
        
    config.pop(msg)
    saveConfig(config)
    await bot.send(ev, f'取消定义汇率[{msg}]成功')
            