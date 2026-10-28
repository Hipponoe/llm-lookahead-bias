"""
新闻采集器 - 实时获取RSS新闻并保存到CSV
功能：
1. 增量更新：读取已有CSV，只添加新新闻
2. 唯一ID标识：每条新闻有唯一序号
3. 首次运行：抓取最近5天的历史新闻
"""

from openai import OpenAI
import feedparser
import requests
from newspaper import Article
from datetime import datetime, timedelta
import time
import pytz
from dateutil import parser
import csv
import os
import hashlib

# ====================== 火山引擎 配置 ======================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_NAME = "deepseek-v3-2-251201"
# ==========================================================

openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=BASE_URL)

# RSS源地址列表
rss_feeds = {
    "💲 华尔街见闻": {
        "华尔街见闻": "https://dedicated.wallstreetcn.com/rss.xml",
    },
    "💻 36氪": {
        "36氪": "https://36kr.com/feed",
    },
    "🇨🇳 中国经济": {
        "东方财富": "http://rss.eastmoney.com/rss_partener.xml",
        # "百度股票焦点": "http://news.baidu.com/n?cmd=1&class=stock&tn=rss&sub=0",
        "中新网": "https://www.chinanews.com.cn/rss/finance.xml",
        "国家统计局-最新发布": "https://www.stats.gov.cn/sj/zxfb/rss.xml",
    },
}

# CSV文件路径
CSV_FILE = "news_database.csv"

# 获取北京时间
def get_beijing_time():
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz)

# 生成唯一ID（基于标题+链接+时间的哈希）
def generate_unique_id(title, link, published):
    unique_str = f"{title}{link}{published}"
    return hashlib.md5(unique_str.encode('utf-8')).hexdigest()[:12]

# 检查新闻是否在指定天数内
def is_within_days(published_str, days=5):
    try:
        beijing_tz = pytz.timezone("Asia/Shanghai")
        cutoff_date = get_beijing_time() - timedelta(days=days)
        
        pub_dt = parser.parse(published_str)
        if pub_dt.tzinfo is None:
            pub_dt = beijing_tz.localize(pub_dt)
        pub_date = pub_dt.astimezone(beijing_tz)
        
        return pub_date >= cutoff_date
    except:
        return False

# 爬取网页正文
def fetch_article_text(url):
    try:
        article = Article(url, language='zh')
        article.download()
        article.parse()
        text = article.text.strip()
        if len(text) > 2000:
            text = text[:2000] + "..."
        return text if text else "（无正文内容）"
    except Exception as e:
        return f"（爬取失败：{str(e)}）"

# 带UA请求RSS
def fetch_feed_with_headers(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        return feedparser.parse(response.content)
    except:
        return feedparser.parse(url)

# 重试机制
def fetch_feed_with_retry(url, retries=2, delay=3):
    for i in range(retries):
        feed = fetch_feed_with_headers(url)
        if feed and hasattr(feed, 'entries') and len(feed.entries) > 0:
            return feed
        time.sleep(delay)
    return None

# 读取已有CSV中的新闻ID集合
def load_existing_ids():
    if not os.path.exists(CSV_FILE):
        return set()
    
    existing_ids = set()
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_ids.add(row['id'])
    except Exception as e:
        print(f"⚠️ 读取CSV文件失败：{e}")
    
    return existing_ids

# 读取已有CSV中的所有新闻（返回列表）
def load_existing_news():
    if not os.path.exists(CSV_FILE):
        return []
    
    news_list = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                news_list.append(row)
    except Exception as e:
        print(f"⚠️ 读取CSV文件失败：{e}")
    
    return news_list

# 保存新闻到CSV（追加模式）
def save_news_to_csv(news_list, mode='a'):
    fieldnames = ['id', 'source', 'published', 'title', 'link', 'summary', 'content']
    
    file_exists = os.path.exists(CSV_FILE)
    
    with open(CSV_FILE, mode, encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        # 如果是追加模式且文件不存在，先写表头
        if mode == 'a' and not file_exists:
            writer.writeheader()
        elif mode == 'w':
            writer.writeheader()
        
        for news in news_list:
            writer.writerow(news)

# 获取新闻（支持历史抓取和增量更新）
def fetch_news(historical_days=5):
    all_news = []
    existing_ids = load_existing_ids()
    
    if historical_days > 0:
        print(f"📅 正在抓取最近 {historical_days} 天的财经新闻...\n")
    else:
        print(f"📅 正在抓取RSS源最新新闻（增量更新模式）...\n")
    
    for category, sources in rss_feeds.items():
        for source_name, url in sources.items():
            print(f"📡 获取 {source_name} 新闻...")
            feed = fetch_feed_with_retry(url)
            if not feed:
                continue

            count = 0
            new_count = 0
            
            for entry in feed.entries:
                # 过滤时间范围
                published = entry.get("published", "")
                
                if historical_days > 0:
                    # 首次运行：只抓取指定天数内的新闻
                    if not is_within_days(published, historical_days):
                        continue
                else:
                    # 增量模式：不限制时间，只要不在数据库中就添加
                    # 但为了避免抓取太久远的新闻，设置一个合理的上限（5天）
                    if not is_within_days(published, 5):
                        continue

                # 生成唯一ID
                title = entry.get("title", "无标题")
                link = entry.get("link", entry.get("guid", ""))
                news_id = generate_unique_id(title, link, published)
                
                # 跳过已存在的新闻
                if news_id in existing_ids:
                    continue

                # 新闻基础信息
                summary = entry.get("summary", "无摘要")
                content = fetch_article_text(link) if link else "无链接"

                news_item = {
                    'id': news_id,
                    'source': source_name,
                    'published': published,
                    'title': title,
                    'link': link,
                    'summary': summary,
                    'content': content
                }
                all_news.append(news_item)
                existing_ids.add(news_id)
                new_count += 1
                count += 1
                print(f"✅ 新增：{title[:50]}...")

            print(f"🔹 {source_name} 本次抓取：{count} 条，新增：{new_count} 条\n")

    print(f"\n📊 本次总计新增：{len(all_news)} 条新闻")
    return all_news

# 主函数
if __name__ == "__main__":
    # 判断是否是首次运行
    is_first_run = not os.path.exists(CSV_FILE)
    
    if is_first_run:
        print("🆕 检测到首次运行，将抓取最近5天的历史新闻...\n")
        news_list = fetch_news(historical_days=5)
        if news_list:
            save_news_to_csv(news_list, mode='w')
            print(f"✅ 历史数据已保存至 {CSV_FILE}")
    else:
        print("🔄 检测到已有数据，将进行增量更新...\n")
        existing_count = len(load_existing_news())
        print(f"📊 当前数据库已有 {existing_count} 条新闻\n")
        
        news_list = fetch_news(historical_days=0)  # 只抓取今日新闻
        if news_list:
            save_news_to_csv(news_list, mode='a')
            print(f"✅ 增量数据已追加至 {CSV_FILE}")
        else:
            print("ℹ️ 暂无新新闻")
    
    # 显示统计信息
    final_count = len(load_existing_news())
    print(f"\n📈 数据库总计：{final_count} 条新闻")
