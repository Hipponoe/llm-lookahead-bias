"""
行情验证器 - 基于实际行情数据验证预测准确率（增量更新模式）
功能：
1. 读取分析结果CSV
2. 检查已有验证结果，跳过已验证的股票
3. 只验证新增的预测
4. 获取每只股票在新闻发布后1天、3天、5天的涨跌幅
5. 统计预测准确率并保存结果
"""

import csv
import os
from datetime import datetime, timedelta
import pytz
import akshare as ak
import pandas as pd
import time
from dateutil import parser

# 输入输出文件路径
INPUT_CSV = "news_analysis_result.csv"
NEWS_CSV = "news_database.csv"
OUTPUT_CSV = "accuracy_result.csv"
STATS_CSV = "accuracy_statistics.csv"

# 获取北京时间
def get_beijing_time():
    tz = pytz.timezone("Asia/Shanghai")
    return datetime.now(tz)

# 从股票代码中提取纯数字代码
def extract_stock_code(code_str):
    """提取股票代码，如 '贵州茅台(600519)' -> '600519'"""
    if not code_str or code_str == '':
        return None
    
    # 匹配括号中的数字
    import re
    match = re.search(r'\((\d{6})\)', code_str)
    if match:
        return match.group(1)
    
    # 如果本身就是6位数字
    if re.match(r'^\d{6}$', code_str.strip()):
        return code_str.strip()
    
    return None

# 解析发布时间
def parse_published_date(published_str):
    """解析发布时间字符串为datetime对象"""
    try:
        beijing_tz = pytz.timezone("Asia/Shanghai")
        pub_dt = parser.parse(published_str)
        if pub_dt.tzinfo is None:
            pub_dt = beijing_tz.localize(pub_dt)
        return pub_dt.astimezone(beijing_tz)
    except:
        return None

def get_stock_symbol(code):
    """自动给股票代码加上 sh 或 sz 前缀"""
    if code.startswith(("6", "9")):
        return f"sh{code}"  # 沪市
    elif code.startswith(("0", "3", "8")):
        return f"sz{code}"  # 深市
    else:
        return f"sh{code}"  # 默认
# 获取股票历史行情数据
def get_stock_history_data(stock_code, start_date, end_date, retries=3):
    """
    使用akshare和讯接口获取股票历史行情（带重试机制）
    返回DataFrame，包含日期和收盘价
    """
    for attempt in range(retries):
        try:
            # 转换日期格式为YYYYMMDD
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            symbol = get_stock_symbol(stock_code)
            
            # 使用和讯接口获取日线数据
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_str,
                end_date=end_str,
                adjust="qfq"
            )            
            if df is None or df.empty:
                return None
                        
            # 和讯接口返回的列名：date, open, close, high, low, volume
            if 'date' in df.columns and 'close' in df.columns:
                # 重命列为统一格式
                df = df.rename(columns={'date': '日期', 'close': '收盘'})
                
                # 统一转换为datetime64[ns]类型，避免类型比较错误
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                df = df.dropna(subset=['日期'])  # 删除日期解析失败的行
                
                if df.empty:
                    return None
                
                df = df.sort_values('日期').reset_index(drop=True)
                return df
            else:
                print(f"   ⚠️ {stock_code} 数据列名异常: {list(df.columns)}")
                return None
            
        except Exception as e:
            if attempt < retries - 1:
                print(f"   ⚠️ 获取 {stock_code} 数据失败（尝试 {attempt+1}/{retries}）：{str(e)}")
                time.sleep(2)  # 重试前等待2秒
            else:
                print(f"   ⚠️ 获取 {stock_code} 数据失败（已重试{retries}次）：{str(e)}")
                return None

# 计算指定天数后的涨跌幅
def calculate_return(stock_code, publish_date, days_after):
    """
    计算股票在新闻发布后指定天数的涨跌幅
    返回：涨跌幅百分比，如果无法计算则返回None
    """
    try:
        # 确定查询时间范围
        start_date = publish_date - timedelta(days=5)  # 提前5天确保有基准价格
        end_date = publish_date + timedelta(days=days_after + 5)  # 延后确保能获取到目标日期数据
        
        # 获取历史数据
        df = get_stock_history_data(stock_code, start_date, end_date)
        
        if df is None or df.empty:
            return None
        
        # 找到新闻发布日的收盘价（基准价格）
        # 将publish_date转换为日期对象（只保留日期部分）
        publish_date_only = pd.Timestamp(publish_date).date()
        
        # 方法1：精确匹配发布日期（将df['日期']也转换为date类型进行比较）
        base_mask = df['日期'].dt.date == publish_date_only
        base_row = df[base_mask]
        
        if base_row.empty:
            # 方法2：如果发布日是非交易日，找之前最近的交易日
            base_row = df[df['日期'].dt.date <= publish_date_only]
            if base_row.empty:
                return None
            base_row = base_row.iloc[-1:]
        
        base_price = base_row['收盘'].values[0]
        
        # 找到N天后的收盘价
        target_date_only = (pd.Timestamp(publish_date) + pd.Timedelta(days=days_after)).date()
        
        # 方法1：精确匹配目标日期
        target_mask = df['日期'].dt.date == target_date_only
        target_row = df[target_mask]
        
        if target_row.empty:
            # 方法2：如果目标日期是非交易日，找之后最近的交易日
            target_row = df[df['日期'].dt.date >= target_date_only]
            if target_row.empty:
                return None
            target_row = target_row.iloc[:1]
        
        target_price = target_row['收盘'].values[0]
        
        # 计算涨跌幅
        if base_price == 0:
            return None
        
        return_pct = ((target_price - base_price) / base_price) * 100
        return round(return_pct, 2)
    
    except Exception as e:
        print(f"   ⚠️ 计算 {stock_code} {days_after}天后涨跌幅失败：{str(e)}")
        return None

# 读取分析结果CSV
def load_analysis_results():
    if not os.path.exists(INPUT_CSV):
        print(f"❌ 文件不存在：{INPUT_CSV}")
        return []
    
    results = []
    try:
        with open(INPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                results.append(row)
    except Exception as e:
        print(f"❌ 读取CSV文件失败：{e}")
        return []
    
    print(f"📊 已加载 {len(results)} 条分析结果")
    return results

# 读取新闻CSV（获取发布时间）
def load_news_database():
    if not os.path.exists(NEWS_CSV):
        print(f"❌ 文件不存在：{NEWS_CSV}")
        return {}
    
    news_dict = {}
    try:
        with open(NEWS_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                news_dict[row['id']] = row
    except Exception as e:
        print(f"❌ 读取CSV文件失败：{e}")
        return {}
    
    print(f"📊 已加载 {len(news_dict)} 条新闻基础数据")
    return news_dict

# 读取已验证的结果集合
def load_verified_results():
    """读取已经验证过的结果（news_id + stock_code组合）"""
    if not os.path.exists(OUTPUT_CSV):
        return set()
    
    verified_keys = set()
    try:
        with open(OUTPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 使用 news_id + stock_code + prediction_type 作为唯一标识
                key = f"{row['news_id']}_{row['stock_code']}_{row['prediction_type']}"
                verified_keys.add(key)
    except Exception as e:
        print(f"⚠️ 读取验证结果文件失败：{e}")
    
    return verified_keys

# 追加保存验证结果到CSV
def append_accuracy_results(results):
    """追加新的验证结果到CSV文件"""
    fieldnames = [
        'news_id', 'published', 'source', 'core_sectors',  # 新增 source 字段
        'stock_code', 'prediction_type',  # up/down
        'return_1d', 'return_3d', 'return_5d',
        'is_correct_1d', 'is_correct_3d', 'is_correct_5d'
    ]
    
    file_exists = os.path.exists(OUTPUT_CSV)
    
    with open(OUTPUT_CSV, 'a', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        
        # 如果文件不存在，先写表头
        if not file_exists:
            writer.writeheader()
        
        for result in results:
            writer.writerow(result)
    
    print(f"✅ 新增 {len(results)} 条验证结果已保存至 {OUTPUT_CSV}")

# 按来源统计准确率
def calculate_accuracy_by_source(all_results_df):
    """按新闻来源统计预测准确率"""
    if all_results_df.empty:
        return {}
    
    source_stats = {}
    
    # 获取所有唯一来源
    sources = all_results_df['source'].unique()
    
    for source in sources:
        source_data = all_results_df[all_results_df['source'] == source]
        
        stats = {}
        for period in ['1d', '3d', '5d']:
            valid_col = f'is_correct_{period}'
            valid_data = source_data[source_data[valid_col] != '']  # 排除空值
            
            if len(valid_data) > 0:
                total = len(valid_data)
                correct = valid_data[valid_col].astype(int).sum()
                accuracy = (correct / total) * 100
                stats[f'{period}'] = {
                    'total': total,
                    'correct': correct,
                    'accuracy': f"{accuracy:.2f}%"
                }
            else:
                stats[f'{period}'] = {
                    'total': 0,
                    'correct': 0,
                    'accuracy': 'N/A'
                }
        
        source_stats[source] = stats
    
    return source_stats

# 保存统计数据（包含按来源分类）
def save_statistics(stats, source_stats):
    fieldnames = [
        'metric', '1_day', '3_days', '5_days'
    ]
    
    with open(STATS_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 写入总体统计
        for metric, values in stats.items():
            row = {'metric': metric}
            row.update(values)
            writer.writerow(row)
        
        # 写入空行分隔
        writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        writer.writerow({'metric': '=== 按来源分类 ===', '1_day': '', '3_days': '', '5_days': ''})
        
        # 写入各来源统计
        for source, periods in source_stats.items():
            # 来源名称行
            writer.writerow({'metric': f'【{source}】', '1_day': '', '3_days': '', '5_days': ''})
            
            # 有效预测数
            writer.writerow({
                'metric': '  有效预测数',
                '1_day': str(periods['1d']['total']),
                '3_days': str(periods['3d']['total']),
                '5_days': str(periods['5d']['total'])
            })
            
            # 正确预测数
            writer.writerow({
                'metric': '  正确预测数',
                '1_day': str(periods['1d']['correct']),
                '3_days': str(periods['3d']['correct']),
                '5_days': str(periods['5d']['correct'])
            })
            
            # 准确率
            writer.writerow({
                'metric': '  预测准确率',
                '1_day': periods['1d']['accuracy'],
                '3_days': periods['3d']['accuracy'],
                '5_days': periods['5d']['accuracy']
            })
            
            # 空行分隔不同来源
            writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
    
    print(f"✅ 统计数据已保存至 {STATS_CSV}")

# 主函数
if __name__ == "__main__":
    print("🚀 开始行情验证（增量更新模式）...\n")
    
    # 1. 加载数据
    analysis_results = load_analysis_results()
    news_database = load_news_database()
    
    if not analysis_results:
        print("❌ 没有可验证的分析结果")
        exit()
    
    # 2. 加载已验证的结果
    verified_keys = load_verified_results()
    print(f"📊 已验证过的预测：{len(verified_keys)} 条\n")
    
    # 3. 逐条验证（增量模式）
    all_results = []
    total_predictions = 0
    correct_predictions = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions = {'1d': 0, '3d': 0, '5d': 0}
    skipped_count = 0
    
    for idx, analysis in enumerate(analysis_results, 1):
        print(f"\n📈 正在验证第 {idx}/{len(analysis_results)} 条新闻...")
        
        news_id = analysis['news_id']
        published = analysis['published']
        core_sectors = analysis['core_sectors']
        
        # 获取新闻发布时间
        if news_id not in news_database:
            print(f"   ⚠️ 未找到新闻 {news_id} 的基础信息")
            continue
        
        # 获取新闻来源
        source = news_database[news_id].get('source', '未知来源')
        
        publish_date = parse_published_date(published)
        if not publish_date:
            print(f"   ⚠️ 无法解析发布时间")
            continue
        
        # 处理上涨预测
        for i in range(1, 4):
            up_code_key = f'up_code_{i}'
            up_reason_key = f'up_reason_{i}'
            
            stock_code_str = analysis.get(up_code_key, '')
            reason = analysis.get(up_reason_key, '')
            
            if not stock_code_str or stock_code_str == '':
                continue
            
            stock_code = extract_stock_code(stock_code_str)
            if not stock_code:
                print(f"   ⚠️ 无法提取股票代码：{stock_code_str}")
                continue
            
            # 检查是否已验证过
            verify_key = f"{news_id}_{stock_code}_up"
            if verify_key in verified_keys:
                skipped_count += 1
                continue
            
            print(f"   🔍 验证上涨预测：{stock_code_str} (来源: {source})")
            
            # 计算1天、3天、5天后的涨跌幅
            return_1d = calculate_return(stock_code, publish_date, 1)
            return_3d = calculate_return(stock_code, publish_date, 3)
            return_5d = calculate_return(stock_code, publish_date, 5)
            
            # 判断预测是否正确（上涨预测：涨跌幅>0为正确）
            is_correct_1d = 1 if return_1d is not None and return_1d > 0 else 0
            is_correct_3d = 1 if return_3d is not None and return_3d > 0 else 0
            is_correct_5d = 1 if return_5d is not None and return_5d > 0 else 0
            
            # 统计
            if return_1d is not None:
                valid_predictions['1d'] += 1
                correct_predictions['1d'] += is_correct_1d
            if return_3d is not None:
                valid_predictions['3d'] += 1
                correct_predictions['3d'] += is_correct_3d
            if return_5d is not None:
                valid_predictions['5d'] += 1
                correct_predictions['5d'] += is_correct_5d
            
            total_predictions += 1
            
            result_row = {
                'news_id': news_id,
                'published': published,
                'source': source,  # 新增来源字段
                'core_sectors': core_sectors,
                'stock_code': stock_code,
                'prediction_type': 'up',
                'return_1d': return_1d if return_1d is not None else '',
                'return_3d': return_3d if return_3d is not None else '',
                'return_5d': return_5d if return_5d is not None else '',
                'is_correct_1d': is_correct_1d,
                'is_correct_3d': is_correct_3d,
                'is_correct_5d': is_correct_5d
            }
            all_results.append(result_row)
            
            # 避免API限流
            time.sleep(1)
        
        # 处理下跌预测
        for i in range(1, 4):
            down_code_key = f'down_code_{i}'
            down_reason_key = f'down_reason_{i}'
            
            stock_code_str = analysis.get(down_code_key, '')
            reason = analysis.get(down_reason_key, '')
            
            if not stock_code_str or stock_code_str == '':
                continue
            
            stock_code = extract_stock_code(stock_code_str)
            if not stock_code:
                print(f"   ⚠️ 无法提取股票代码：{stock_code_str}")
                continue
            
            # 检查是否已验证过
            verify_key = f"{news_id}_{stock_code}_down"
            if verify_key in verified_keys:
                skipped_count += 1
                continue
            
            print(f"   🔍 验证下跌预测：{stock_code_str} (来源: {source})")
            
            # 计算1天、3天、5天后的涨跌幅
            return_1d = calculate_return(stock_code, publish_date, 1)
            return_3d = calculate_return(stock_code, publish_date, 3)
            return_5d = calculate_return(stock_code, publish_date, 5)
            
            # 判断预测是否正确（下跌预测：涨跌幅<0为正确）
            is_correct_1d = 1 if return_1d is not None and return_1d < 0 else 0
            is_correct_3d = 1 if return_3d is not None and return_3d < 0 else 0
            is_correct_5d = 1 if return_5d is not None and return_5d < 0 else 0
            
            # 统计
            if return_1d is not None:
                valid_predictions['1d'] += 1
                correct_predictions['1d'] += is_correct_1d
            if return_3d is not None:
                valid_predictions['3d'] += 1
                correct_predictions['3d'] += is_correct_3d
            if return_5d is not None:
                valid_predictions['5d'] += 1
                correct_predictions['5d'] += is_correct_5d
            
            total_predictions += 1
            
            result_row = {
                'news_id': news_id,
                'published': published,
                'source': source,  # 新增来源字段
                'core_sectors': core_sectors,
                'stock_code': stock_code,
                'prediction_type': 'down',
                'return_1d': return_1d if return_1d is not None else '',
                'return_3d': return_3d if return_3d is not None else '',
                'return_5d': return_5d if return_5d is not None else '',
                'is_correct_1d': is_correct_1d,
                'is_correct_3d': is_correct_3d,
                'is_correct_5d': is_correct_5d
            }
            all_results.append(result_row)
            
            # 避免API限流
            time.sleep(1)
    
    # 4. 保存详细结果
    if all_results:
        append_accuracy_results(all_results)
    
    # 5. 计算并保存统计数据（包含按来源分类）
    stats = {}
    
    for period in ['1d', '3d', '5d']:
        if valid_predictions[period] > 0:
            accuracy = (correct_predictions[period] / valid_predictions[period]) * 100
            stats[f'accuracy_{period}'] = {
                '1_day': f"{accuracy:.2f}%" if period == '1d' else '',
                '3_days': f"{accuracy:.2f}%" if period == '3d' else '',
                '5_days': f"{accuracy:.2f}%" if period == '5d' else ''
            }
        else:
            stats[f'accuracy_{period}'] = {
                '1_day': 'N/A' if period == '1d' else '',
                '3_days': 'N/A' if period == '3d' else '',
                '5_days': 'N/A' if period == '5d' else ''
            }
    
    # 重新组织统计数据格式
    stats_formatted = {
        '预测准确率': {
            '1_day': f"{(correct_predictions['1d']/valid_predictions['1d']*100) if valid_predictions['1d'] > 0 else 0:.2f}%",
            '3_days': f"{(correct_predictions['3d']/valid_predictions['3d']*100) if valid_predictions['3d'] > 0 else 0:.2f}%",
            '5_days': f"{(correct_predictions['5d']/valid_predictions['5d']*100) if valid_predictions['5d'] > 0 else 0:.2f}%"
        },
        '有效预测数': {
            '1_day': str(valid_predictions['1d']),
            '3_days': str(valid_predictions['3d']),
            '5_days': str(valid_predictions['5d'])
        },
        '正确预测数': {
            '1_day': str(correct_predictions['1d']),
            '3_days': str(correct_predictions['3d']),
            '5_days': str(correct_predictions['5d'])
        },
        '总预测数': {
            '1_day': str(total_predictions),
            '3_days': str(total_predictions),
            '5_days': str(total_predictions)
        }
    }
    
    # 按来源统计准确率
    if all_results:
        import pandas as pd
        all_results_df = pd.DataFrame(all_results)
        source_stats = calculate_accuracy_by_source(all_results_df)
    else:
        source_stats = {}
    
    save_statistics(stats_formatted, source_stats)
    
    # 6. 打印统计摘要
    print("\n" + "="*60)
    print("📊 预测准确率统计摘要（总体）")
    print("="*60)
    print(f"本次新增验证数：{total_predictions}")
    print(f"跳过已验证数：{skipped_count}")
    print(f"\n1天后准确率：{correct_predictions['1d']}/{valid_predictions['1d']} = {(correct_predictions['1d']/valid_predictions['1d']*100) if valid_predictions['1d'] > 0 else 0:.2f}%")
    print(f"3天后准确率：{correct_predictions['3d']}/{valid_predictions['3d']} = {(correct_predictions['3d']/valid_predictions['3d']*100) if valid_predictions['3d'] > 0 else 0:.2f}%")
    print(f"5天后准确率：{correct_predictions['5d']}/{valid_predictions['5d']} = {(correct_predictions['5d']/valid_predictions['5d']*100) if valid_predictions['5d'] > 0 else 0:.2f}%")
    
    # 打印按来源分类的统计
    if source_stats:
        print("\n" + "="*60)
        print("📊 预测准确率统计摘要（按来源分类）")
        print("="*60)
        for source, periods in source_stats.items():
            print(f"\n【{source}】")
            for period_name, period_data in periods.items():
                days_map = {'1d': '1天', '3d': '3天', '5d': '5天'}
                days_cn = days_map.get(period_name, period_name)
                print(f"  {days_cn}后: {period_data['accuracy']} ({period_data['correct']}/{period_data['total']})")
    
    print("="*60)
    print("\n✅ 验证完成！")
