"""
新闻分析器 - 使用AI分析新闻对A股的影响（增量更新模式）
功能：
1. 读取新闻CSV文件
2. 检查已有分析结果，跳过已分析的新闻
3. 只分析新增的新闻
4. 输出分析结果到新的CSV文件
"""

from openai import OpenAI
import csv
import os
import time
from datetime import datetime
import pytz

# ====================== 火山引擎 配置 ======================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_NAME = "deepseek-v4-flash-260425"
# ==========================================================

openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)

# 输入输出文件路径
INPUT_CSV = "news_database.csv"
OUTPUT_CSV = "news_analysis_result.csv"

# 获取北京时间
def get_beijing_time():
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz)

# AI 分析单条新闻
def analyze_single_news(news):
    prompt = f"""
你是专业A股分析师，请严格根据下面**单条新闻**进行分析。

【新闻内容】
标题：{news['title']}
链接：{news['link']}
发布时间：{news['published']}
正文：{news['content']}

【分析要求】
1. 判断新闻影响的**A股核心板块**（1-3个，用逗号分隔）
2. 输出**最可能上涨的3只股票**（必须带股票代码，格式：贵州茅台(600519)）
3. 输出**最可能下跌的3只股票**（同上）
4. 每只股票必须写**明确理由**（简洁明了，不超过50字）
5. 若无直接影响则写：无

【输出格式】（严格按此格式，不要添加其他内容）
核心板块：板块1,板块2,板块3
上涨代码1：股票代码1
上涨理由1：理由内容
上涨代码2：股票代码2
上涨理由2：理由内容
上涨代码3：股票代码3
上涨理由3：理由内容
下跌代码1：股票代码1
下跌理由1：理由内容
下跌代码2：股票代码2
下跌理由2：理由内容
下跌代码3：股票代码3
下跌理由3：理由内容
"""
    try:
        completion = openai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是专业A股市场分析师，只输出客观、精准的分析结果。严格按照指定格式输出。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ 分析失败：{str(e)}")
        return None

# 解析AI分析结果
def parse_analysis_result(analysis_text):
    result = {
        'core_sectors': '',
        'up_codes': ['', '', ''],
        'up_reasons': ['', '', ''],
        'down_codes': ['', '', ''],
        'down_reasons': ['', '', '']
    }
    
    if not analysis_text or '无' in analysis_text:
        result['core_sectors'] = '无直接影响'
        return result
    
    lines = analysis_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if line.startswith('核心板块：'):
            result['core_sectors'] = line.replace('核心板块：', '').strip()
        elif line.startswith('上涨代码1：'):
            result['up_codes'][0] = line.replace('上涨代码1：', '').strip()
        elif line.startswith('上涨理由1：'):
            result['up_reasons'][0] = line.replace('上涨理由1：', '').strip()
        elif line.startswith('上涨代码2：'):
            result['up_codes'][1] = line.replace('上涨代码2：', '').strip()
        elif line.startswith('上涨理由2：'):
            result['up_reasons'][1] = line.replace('上涨理由2：', '').strip()
        elif line.startswith('上涨代码3：'):
            result['up_codes'][2] = line.replace('上涨代码3：', '').strip()
        elif line.startswith('上涨理由3：'):
            result['up_reasons'][2] = line.replace('上涨理由3：', '').strip()
        elif line.startswith('下跌代码1：'):
            result['down_codes'][0] = line.replace('下跌代码1：', '').strip()
        elif line.startswith('下跌理由1：'):
            result['down_reasons'][0] = line.replace('下跌理由1：', '').strip()
        elif line.startswith('下跌代码2：'):
            result['down_codes'][1] = line.replace('下跌代码2：', '').strip()
        elif line.startswith('下跌理由2：'):
            result['down_reasons'][1] = line.replace('下跌理由2：', '').strip()
        elif line.startswith('下跌代码3：'):
            result['down_codes'][2] = line.replace('下跌代码3：', '').strip()
        elif line.startswith('下跌理由3：'):
            result['down_reasons'][2] = line.replace('下跌理由3：', '').strip()
    
    return result

# 读取已分析的新闻ID集合
def load_analyzed_ids():
    """读取已经分析过的新闻ID"""
    if not os.path.exists(OUTPUT_CSV):
        return set()
    
    analyzed_ids = set()
    try:
        with open(OUTPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                analyzed_ids.add(row['news_id'])
    except Exception as e:
        print(f"⚠️ 读取分析结果文件失败：{e}")
    
    return analyzed_ids

# 读取新闻CSV
def load_news_from_csv():
    if not os.path.exists(INPUT_CSV):
        print(f"❌ 文件不存在：{INPUT_CSV}")
        return []
    
    news_list = []
    try:
        with open(INPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                news_list.append(row)
    except Exception as e:
        print(f"❌ 读取CSV文件失败：{e}")
        return []
    
    print(f"📊 已加载 {len(news_list)} 条新闻")
    return news_list

# 追加保存分析结果到CSV
def append_analysis_results(results):
    """追加新的分析结果到CSV文件"""
    fieldnames = [
        'news_id', 'published', 'core_sectors',
        'up_code_1', 'up_reason_1',
        'up_code_2', 'up_reason_2',
        'up_code_3', 'up_reason_3',
        'down_code_1', 'down_reason_1',
        'down_code_2', 'down_reason_2',
        'down_code_3', 'down_reason_3'
    ]
    
    file_exists = os.path.exists(OUTPUT_CSV)
    
    with open(OUTPUT_CSV, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        # 如果文件不存在，先写表头
        if not file_exists:
            writer.writeheader()
        
        for result in results:
            writer.writerow(result)
    
    print(f"✅ 新增 {len(results)} 条分析结果已保存至 {OUTPUT_CSV}")

# 主函数
if __name__ == "__main__":
    print("🚀 开始新闻分析（增量更新模式）...\n")
    
    # 1. 加载新闻
    news_list = load_news_from_csv()
    if not news_list:
        print("❌ 没有可分析的新闻")
        exit()
    
    # 2. 加载已分析的新闻ID
    analyzed_ids = load_analyzed_ids()
    print(f"📊 已分析过的新闻：{len(analyzed_ids)} 条\n")
    
    # 3. 筛选出未分析的新闻
    unanalyzed_news = [news for news in news_list if news['id'] not in analyzed_ids]
    
    if not unanalyzed_news:
        print("✅ 所有新闻都已分析过，无需更新")
        exit()
    
    print(f"🆕 待分析的新新闻：{len(unanalyzed_news)} 条\n")
    
    # 4. 逐条分析新新闻
    analysis_results = []
    total = len(unanalyzed_news)
    
    for idx, news in enumerate(unanalyzed_news, 1):
        print(f"\n🤖 正在分析第 {idx}/{total} 条新新闻...")
        print(f"   标题：{news['title'][:50]}...")
        
        # AI分析
        analysis_text = analyze_single_news(news)
        
        if analysis_text:
            # 解析结果
            parsed = parse_analysis_result(analysis_text)
            
            result_row = {
                'news_id': news['id'],
                'published': news['published'],
                'core_sectors': parsed['core_sectors'],
                'up_code_1': parsed['up_codes'][0],
                'up_reason_1': parsed['up_reasons'][0],
                'up_code_2': parsed['up_codes'][1],
                'up_reason_2': parsed['up_reasons'][1],
                'up_code_3': parsed['up_codes'][2],
                'up_reason_3': parsed['up_reasons'][2],
                'down_code_1': parsed['down_codes'][0],
                'down_reason_1': parsed['down_reasons'][0],
                'down_code_2': parsed['down_codes'][1],
                'down_reason_2': parsed['down_reasons'][1],
                'down_code_3': parsed['down_codes'][2],
                'down_reason_3': parsed['down_reasons'][2]
            }
            analysis_results.append(result_row)
            print(f"   ✅ 分析完成")
        else:
            print(f"   ❌ 分析失败，跳过")
        
        # 避免API限流，每次请求间隔1秒
        if idx < total:
            time.sleep(1)
    
    # 5. 追加保存新结果
    if analysis_results:
        append_analysis_results(analysis_results)
        print(f"\n📈 本次完成 {len(analysis_results)} 条新新闻分析")
        
        # 显示总计
        total_analyzed = len(analyzed_ids) + len(analysis_results)
        print(f"📊 累计已分析：{total_analyzed} 条新闻")
    else:
        print("\n❌ 没有成功的分析结果")
