"""
行情验证器 - 基于实际行情数据验证预测准确率（增量更新模式）
功能：
1. 读取分析结果CSV
2. 检查已有验证结果，跳过已验证的股票
3. 只验证新增的预测（增量更新，补缺失值）
4. 获取每只股票在新闻发布后1天、3天、5天的涨跌幅
5. 统计预测准确率并保存结果
6. 按方向（上涨/下跌）分别统计准确率
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

# 格式化发布时间（统一格式）
def format_published_date(pub_date):
    """统一发布时间格式为 YYYY-MM-DD HH:MM:SS"""
    if isinstance(pub_date, str):
        try:
            pub_date = parser.parse(pub_date)
        except:
            return pub_date
    
    if isinstance(pub_date, datetime):
        if pub_date.tzinfo is None:
            pub_date = pytz.timezone("Asia/Shanghai").localize(pub_date)
        return pub_date.strftime("%Y-%m-%d %H:%M:%S")
    
    return str(pub_date)

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
    返回：涨跌幅百分比，如果无法计算（数据未获取到）则返回None
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
        publish_date_only = pd.Timestamp(publish_date).date()
        
        # 方法1：精确匹配发布日期
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

# 读取已验证的结果并分析缺失值
def load_existing_results():
    """读取已有的验证结果，返回字典结构用于增量更新"""
    if not os.path.exists(OUTPUT_CSV):
        return {}, set()
    
    existing_results = {}  # key: news_id_stock_code_prediction_type -> result_row
    verified_keys = set()
    
    try:
        with open(OUTPUT_CSV, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = f"{row['news_id']}_{row['stock_code']}_{row['prediction_type']}"
                verified_keys.add(key)
                existing_results[key] = row
    except Exception as e:
        print(f"⚠️ 读取验证结果文件失败：{e}")
    
    return existing_results, verified_keys

# 检查是否需要补全缺失值
def check_missing_returns(row):
    """检查某条记录是否有缺失的收益数据"""
    missing_periods = []
    for period in ['1d', '3d', '5d']:
        return_field = f'return_{period}'
        if return_field in row and (row[return_field] == '' or row[return_field] is None):
            missing_periods.append(period)
    return missing_periods

# 更新单条验证结果
def update_result_row(existing_row, stock_code, publish_date, missing_periods):
    """更新缺失的收益数据"""
    updated = False
    result_row = existing_row.copy()
    
    for period in missing_periods:
        days = 1 if period == '1d' else 3 if period == '3d' else 5
        return_pct = calculate_return(stock_code, publish_date, days)
        
        if return_pct is not None:
            result_row[f'return_{period}'] = return_pct
            # 更新正确性判断
            pred_type = result_row['prediction_type']
            if pred_type == 'up':
                is_correct = 1 if return_pct > 0 else 0
            else:  # down
                is_correct = 1 if return_pct < 0 else 0
            result_row[f'is_correct_{period}'] = is_correct
            updated = True
            print(f"      ✅ 补全 {period} 数据: {return_pct}%")
        else:
            print(f"      ⚠️ 仍无法获取 {period} 数据")
    
    return result_row if updated else None

# 保存或更新验证结果
def save_or_update_results(all_results_dict):
    """保存所有验证结果（完整写入）"""
    fieldnames = [
        'news_id', 'published', 'source', 'core_sectors',
        'stock_code', 'prediction_type',
        'return_1d', 'return_3d', 'return_5d',
        'is_correct_1d', 'is_correct_3d', 'is_correct_5d'
    ]
    
    with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in all_results_dict.values():
            # 确保published字段格式统一
            result['published'] = format_published_date(result['published'])
            writer.writerow(result)
    
    print(f"✅ 已保存 {len(all_results_dict)} 条验证结果至 {OUTPUT_CSV}")

# 按来源统计准确率（按方向和总体）
def calculate_accuracy_by_source(all_results_df):
    """
    按新闻来源统计预测准确率
    返回：包含总体、上涨、下跌的统计
    """
    if all_results_df.empty:
        return {}, {}, {}
    
    source_stats_overall = {}
    source_stats_up = {}
    source_stats_down = {}
    
    # 获取所有唯一来源
    sources = all_results_df['source'].unique()
    
    for source in sources:
        source_data = all_results_df[all_results_df['source'] == source]
        
        # 总体统计
        overall_stats = {}
        # 上涨预测统计
        up_stats = {}
        # 下跌预测统计
        down_stats = {}
        
        for period in ['1d', '3d', '5d']:
            # 总体统计
            valid_col = f'is_correct_{period}'
            valid_data_overall = source_data[source_data[f'return_{period}'].notna() & (source_data[f'return_{period}'] != '')]
            
            if len(valid_data_overall) > 0:
                total = len(valid_data_overall)
                correct = valid_data_overall[valid_col].astype(int).sum()
                accuracy = (correct / total) * 100
                overall_stats[f'{period}'] = {
                    'total': total,
                    'correct': correct,
                    'accuracy': f"{accuracy:.2f}%"
                }
            else:
                overall_stats[f'{period}'] = {
                    'total': 0,
                    'correct': 0,
                    'accuracy': 'N/A'
                }
            
            # 上涨预测统计
            up_data = source_data[(source_data['prediction_type'] == 'up') & 
                                  (source_data[f'return_{period}'].notna()) & 
                                  (source_data[f'return_{period}'] != '')]
            
            if len(up_data) > 0:
                up_total = len(up_data)
                up_correct = up_data[valid_col].astype(int).sum()
                up_accuracy = (up_correct / up_total) * 100
                up_stats[f'{period}'] = {
                    'total': up_total,
                    'correct': up_correct,
                    'accuracy': f"{up_accuracy:.2f}%"
                }
            else:
                up_stats[f'{period}'] = {
                    'total': 0,
                    'correct': 0,
                    'accuracy': 'N/A'
                }
            
            # 下跌预测统计
            down_data = source_data[(source_data['prediction_type'] == 'down') & 
                                    (source_data[f'return_{period}'].notna()) & 
                                    (source_data[f'return_{period}'] != '')]
            
            if len(down_data) > 0:
                down_total = len(down_data)
                down_correct = down_data[valid_col].astype(int).sum()
                down_accuracy = (down_correct / down_total) * 100
                down_stats[f'{period}'] = {
                    'total': down_total,
                    'correct': down_correct,
                    'accuracy': f"{down_accuracy:.2f}%"
                }
            else:
                down_stats[f'{period}'] = {
                    'total': 0,
                    'correct': 0,
                    'accuracy': 'N/A'
                }
        
        source_stats_overall[source] = overall_stats
        source_stats_up[source] = up_stats
        source_stats_down[source] = down_stats
    
    return source_stats_overall, source_stats_up, source_stats_down

# 保存统计数据（包含按来源分类和按方向分类）
def save_statistics(stats_overall, stats_by_direction, source_stats_overall, source_stats_up, source_stats_down):
    fieldnames = [
        'metric', '1_day', '3_days', '5_days'
    ]
    
    with open(STATS_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 写入总体统计（按方向）
        writer.writerow({'metric': '=== 总体统计（按方向） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for direction, stats in stats_by_direction.items():
            direction_name = {'overall': '总体', 'up': '上涨预测', 'down': '下跌预测'}.get(direction, direction)
            writer.writerow({'metric': f'【{direction_name}】', '1_day': '', '3_days': '', '5_days': ''})
            
            # 预测准确率
            writer.writerow({
                'metric': '  预测准确率',
                '1_day': stats['1_day']['accuracy'],
                '3_days': stats['3_days']['accuracy'],
                '5_days': stats['5_days']['accuracy']
            })
            
            # 有效预测数
            writer.writerow({
                'metric': '  有效预测数',
                '1_day': str(stats['1_day']['total']),
                '3_days': str(stats['3_days']['total']),
                '5_days': str(stats['5_days']['total'])
            })
            
            # 正确预测数
            writer.writerow({
                'metric': '  正确预测数',
                '1_day': str(stats['1_day']['correct']),
                '3_days': str(stats['3_days']['correct']),
                '5_days': str(stats['5_days']['correct'])
            })
            
            writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        
        # 写入空行分隔
        writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        writer.writerow({'metric': '=== 总体统计（总体指标） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        # 写入总体统计指标
        for metric, values in stats_overall.items():
            row = {'metric': metric}
            row.update(values)
            writer.writerow(row)
        
        # 写入空行分隔
        writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        writer.writerow({'metric': '=== 按来源分类（总体） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        # 写入各来源总体统计
        for source, periods in source_stats_overall.items():
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
        
        # 写入各来源上涨预测统计
        writer.writerow({'metric': '=== 按来源分类（上涨预测） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for source, periods in source_stats_up.items():
            writer.writerow({'metric': f'【{source}】', '1_day': '', '3_days': '', '5_days': ''})
            
            writer.writerow({
                'metric': '  有效预测数',
                '1_day': str(periods['1d']['total']),
                '3_days': str(periods['3d']['total']),
                '5_days': str(periods['5d']['total'])
            })
            
            writer.writerow({
                'metric': '  正确预测数',
                '1_day': str(periods['1d']['correct']),
                '3_days': str(periods['3d']['correct']),
                '5_days': str(periods['5d']['correct'])
            })
            
            writer.writerow({
                'metric': '  预测准确率',
                '1_day': periods['1d']['accuracy'],
                '3_days': periods['3d']['accuracy'],
                '5_days': periods['5d']['accuracy']
            })
            
            writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        
        # 写入各来源下跌预测统计
        writer.writerow({'metric': '=== 按来源分类（下跌预测） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for source, periods in source_stats_down.items():
            writer.writerow({'metric': f'【{source}】', '1_day': '', '3_days': '', '5_days': ''})
            
            writer.writerow({
                'metric': '  有效预测数',
                '1_day': str(periods['1d']['total']),
                '3_days': str(periods['3d']['total']),
                '5_days': str(periods['5d']['total'])
            })
            
            writer.writerow({
                'metric': '  正确预测数',
                '1_day': str(periods['1d']['correct']),
                '3_days': str(periods['3d']['correct']),
                '5_days': str(periods['5d']['correct'])
            })
            
            writer.writerow({
                'metric': '  预测准确率',
                '1_day': periods['1d']['accuracy'],
                '3_days': periods['3d']['accuracy'],
                '5_days': periods['5d']['accuracy']
            })
            
            writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
    
    print(f"✅ 统计数据已保存至 {STATS_CSV}")

# 主函数
if __name__ == "__main__":
    print("🚀 开始行情验证（增量更新模式 - 自动补全缺失值）...\n")
    
    # 1. 加载数据
    analysis_results = load_analysis_results()
    news_database = load_news_database()
    
    if not analysis_results:
        print("❌ 没有可验证的分析结果")
        exit()
    
    # 2. 加载已有验证结果
    existing_results, verified_keys = load_existing_results()
    print(f"📊 已有验证结果：{len(existing_results)} 条\n")
    
    # 3. 准备存储所有结果（合并已有和新增）
    all_results_dict = existing_results.copy()
    
    # 统计变量（按方向分类）
    # 总体统计
    total_predictions = 0
    correct_predictions_overall = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions_overall = {'1d': 0, '3d': 0, '5d': 0}
    
    # 上涨预测统计
    correct_predictions_up = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions_up = {'1d': 0, '3d': 0, '5d': 0}
    
    # 下跌预测统计
    correct_predictions_down = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions_down = {'1d': 0, '3d': 0, '5d': 0}
    
    new_added_count = 0
    updated_count = 0
    skipped_complete_count = 0
    
    for idx, analysis in enumerate(analysis_results, 1):
        print(f"\n📈 处理第 {idx}/{len(analysis_results)} 条新闻...")
        
        news_id = analysis['news_id']
        published = analysis['published']
        core_sectors = analysis['core_sectors']
        
        # 获取新闻发布时间
        if news_id not in news_database:
            print(f"   ⚠️ 未找到新闻 {news_id} 的基础信息")
            continue
        
        # 格式化发布时间
        formatted_published = format_published_date(published)
        
        # 获取新闻来源
        source = news_database[news_id].get('source', '未知来源')
        
        publish_date = parse_published_date(published)
        if not publish_date:
            print(f"   ⚠️ 无法解析发布时间")
            continue
        
        # 处理上涨预测和下跌预测
        for pred_type in ['up', 'down']:
            for i in range(1, 4):
                code_key = f'{pred_type}_code_{i}'
                stock_code_str = analysis.get(code_key, '')
                
                if not stock_code_str or stock_code_str == '':
                    continue
                
                stock_code = extract_stock_code(stock_code_str)
                if not stock_code:
                    print(f"   ⚠️ 无法提取股票代码：{stock_code_str}")
                    continue
                
                # 生成唯一键
                verify_key = f"{news_id}_{stock_code}_{pred_type}"
                
                # 检查是否已存在
                if verify_key in all_results_dict:
                    existing_row = all_results_dict[verify_key]
                    
                    # 检查是否有缺失值
                    missing_periods = check_missing_returns(existing_row)
                    
                    if missing_periods:
                        print(f"   🔄 更新预测：{stock_code_str} ({pred_type}) - 缺失 {', '.join(missing_periods)}")
                        
                        # 尝试补全缺失数据
                        updated_row = update_result_row(existing_row, stock_code, publish_date, missing_periods)
                        if updated_row:
                            all_results_dict[verify_key] = updated_row
                            updated_count += 1
                            
                            # 更新统计（只更新补全的部分）
                            for period in missing_periods:
                                return_val = updated_row[f'return_{period}']
                                if return_val != '' and return_val is not None:
                                    # 总体统计
                                    valid_predictions_overall[period] += 1
                                    correct_predictions_overall[period] += int(updated_row[f'is_correct_{period}'])
                                    
                                    # 按方向统计
                                    if pred_type == 'up':
                                        valid_predictions_up[period] += 1
                                        correct_predictions_up[period] += int(updated_row[f'is_correct_{period}'])
                                    else:
                                        valid_predictions_down[period] += 1
                                        correct_predictions_down[period] += int(updated_row[f'is_correct_{period}'])
                    else:
                        # 完整数据，但需要统计到总体中（如果是首次遇到）
                        if verify_key not in verified_keys:
                            print(f"   📊 加载已有完整数据：{stock_code_str} ({pred_type})")
                            # 统计已有数据
                            for period in ['1d', '3d', '5d']:
                                return_val = existing_row.get(f'return_{period}', '')
                                if return_val != '' and return_val is not None:
                                    # 总体统计
                                    valid_predictions_overall[period] += 1
                                    correct_predictions_overall[period] += int(existing_row.get(f'is_correct_{period}', 0))
                                    
                                    # 按方向统计
                                    if pred_type == 'up':
                                        valid_predictions_up[period] += 1
                                        correct_predictions_up[period] += int(existing_row.get(f'is_correct_{period}', 0))
                                    else:
                                        valid_predictions_down[period] += 1
                                        correct_predictions_down[period] += int(existing_row.get(f'is_correct_{period}', 0))
                            skipped_complete_count += 1
                        else:
                            # 已经统计过的，跳过
                            pass
                else:
                    # 新增预测
                    print(f"   🆕 新增验证：{stock_code_str} ({pred_type}) 来源: {source}")
                    
                    # 计算收益
                    return_1d = calculate_return(stock_code, publish_date, 1)
                    return_3d = calculate_return(stock_code, publish_date, 3)
                    return_5d = calculate_return(stock_code, publish_date, 5)
                    
                    # 判断正确性
                    if pred_type == 'up':
                        is_correct_1d = 1 if return_1d is not None and return_1d > 0 else 0
                        is_correct_3d = 1 if return_3d is not None and return_3d > 0 else 0
                        is_correct_5d = 1 if return_5d is not None and return_5d > 0 else 0
                    else:  # down
                        is_correct_1d = 1 if return_1d is not None and return_1d < 0 else 0
                        is_correct_3d = 1 if return_3d is not None and return_3d < 0 else 0
                        is_correct_5d = 1 if return_5d is not None and return_5d < 0 else 0
                    
                    # 统计有效数据
                    for period, ret, is_correct in [('1d', return_1d, is_correct_1d), 
                                                     ('3d', return_3d, is_correct_3d),
                                                     ('5d', return_5d, is_correct_5d)]:
                        if ret is not None:
                            # 总体统计
                            valid_predictions_overall[period] += 1
                            correct_predictions_overall[period] += is_correct
                            
                            # 按方向统计
                            if pred_type == 'up':
                                valid_predictions_up[period] += 1
                                correct_predictions_up[period] += is_correct
                            else:
                                valid_predictions_down[period] += 1
                                correct_predictions_down[period] += is_correct
                    
                    total_predictions += 1
                    new_added_count += 1
                    
                    # 创建新记录
                    result_row = {
                        'news_id': news_id,
                        'published': formatted_published,
                        'source': source,
                        'core_sectors': core_sectors,
                        'stock_code': stock_code,
                        'prediction_type': pred_type,
                        'return_1d': return_1d if return_1d is not None else '',
                        'return_3d': return_3d if return_3d is not None else '',
                        'return_5d': return_5d if return_5d is not None else '',
                        'is_correct_1d': is_correct_1d,
                        'is_correct_3d': is_correct_3d,
                        'is_correct_5d': is_correct_5d
                    }
                    all_results_dict[verify_key] = result_row
                    
                    # 避免API限流
                    time.sleep(1)
    
    # 4. 保存所有结果
    if all_results_dict:
        save_or_update_results(all_results_dict)
    
    # 5. 准备统计数据
    # 总体统计指标
    stats_overall = {
        '总预测数': {
            '1_day': str(len(all_results_dict)),
            '3_days': str(len(all_results_dict)),
            '5_days': str(len(all_results_dict))
        },
        '有效预测数': {
            '1_day': str(valid_predictions_overall['1d']),
            '3_days': str(valid_predictions_overall['3d']),
            '5_days': str(valid_predictions_overall['5d'])
        },
        '正确预测数': {
            '1_day': str(correct_predictions_overall['1d']),
            '3_days': str(correct_predictions_overall['3d']),
            '5_days': str(correct_predictions_overall['5d'])
        },
        '预测准确率': {
            '1_day': f"{(correct_predictions_overall['1d']/valid_predictions_overall['1d']*100) if valid_predictions_overall['1d'] > 0 else 0:.2f}%",
            '3_days': f"{(correct_predictions_overall['3d']/valid_predictions_overall['3d']*100) if valid_predictions_overall['3d'] > 0 else 0:.2f}%",
            '5_days': f"{(correct_predictions_overall['5d']/valid_predictions_overall['5d']*100) if valid_predictions_overall['5d'] > 0 else 0:.2f}%"
        }
    }
    
    # 按方向统计
    stats_by_direction = {
        'overall': {
            '1_day': {'total': valid_predictions_overall['1d'], 'correct': correct_predictions_overall['1d'], 
                     'accuracy': f"{(correct_predictions_overall['1d']/valid_predictions_overall['1d']*100) if valid_predictions_overall['1d'] > 0 else 0:.2f}%"},
            '3_days': {'total': valid_predictions_overall['3d'], 'correct': correct_predictions_overall['3d'],
                      'accuracy': f"{(correct_predictions_overall['3d']/valid_predictions_overall['3d']*100) if valid_predictions_overall['3d'] > 0 else 0:.2f}%"},
            '5_days': {'total': valid_predictions_overall['5d'], 'correct': correct_predictions_overall['5d'],
                      'accuracy': f"{(correct_predictions_overall['5d']/valid_predictions_overall['5d']*100) if valid_predictions_overall['5d'] > 0 else 0:.2f}%"}
        },
        'up': {
            '1_day': {'total': valid_predictions_up['1d'], 'correct': correct_predictions_up['1d'],
                     'accuracy': f"{(correct_predictions_up['1d']/valid_predictions_up['1d']*100) if valid_predictions_up['1d'] > 0 else 0:.2f}%"},
            '3_days': {'total': valid_predictions_up['3d'], 'correct': correct_predictions_up['3d'],
                      'accuracy': f"{(correct_predictions_up['3d']/valid_predictions_up['3d']*100) if valid_predictions_up['3d'] > 0 else 0:.2f}%"},
            '5_days': {'total': valid_predictions_up['5d'], 'correct': correct_predictions_up['5d'],
                      'accuracy': f"{(correct_predictions_up['5d']/valid_predictions_up['5d']*100) if valid_predictions_up['5d'] > 0 else 0:.2f}%"}
        },
        'down': {
            '1_day': {'total': valid_predictions_down['1d'], 'correct': correct_predictions_down['1d'],
                     'accuracy': f"{(correct_predictions_down['1d']/valid_predictions_down['1d']*100) if valid_predictions_down['1d'] > 0 else 0:.2f}%"},
            '3_days': {'total': valid_predictions_down['3d'], 'correct': correct_predictions_down['3d'],
                      'accuracy': f"{(correct_predictions_down['3d']/valid_predictions_down['3d']*100) if valid_predictions_down['3d'] > 0 else 0:.2f}%"},
            '5_days': {'total': valid_predictions_down['5d'], 'correct': correct_predictions_down['5d'],
                      'accuracy': f"{(correct_predictions_down['5d']/valid_predictions_down['5d']*100) if valid_predictions_down['5d'] > 0 else 0:.2f}%"}
        }
    }
    
    # 按来源统计准确率
    if all_results_dict:
        all_results_list = list(all_results_dict.values())
        all_results_df = pd.DataFrame(all_results_list)
        # 转换收益列为数值类型
        for period in ['1d', '3d', '5d']:
            all_results_df[f'return_{period}'] = pd.to_numeric(all_results_df[f'return_{period}'], errors='coerce')
        source_stats_overall, source_stats_up, source_stats_down = calculate_accuracy_by_source(all_results_df)
    else:
        source_stats_overall, source_stats_up, source_stats_down = {}, {}, {}
    
    # 6. 保存统计数据
    save_statistics(stats_overall, stats_by_direction, source_stats_overall, source_stats_up, source_stats_down)
    
    # 7. 打印统计摘要
    print("\n" + "="*60)
    print("📊 预测准确率统计摘要")
    print("="*60)
    print(f"本次新增预测数：{new_added_count}")
    print(f"本次补全更新数：{updated_count}")
    print(f"已完整跳过数：{skipped_complete_count}")
    print(f"总预测记录数：{len(all_results_dict)}")
    
    print("\n" + "-"*60)
    print("【总体统计】")
    print("-"*60)
    print(f"1天后准确率：{correct_predictions_overall['1d']}/{valid_predictions_overall['1d']} = {stats_by_direction['overall']['1_day']['accuracy']}")
    print(f"3天后准确率：{correct_predictions_overall['3d']}/{valid_predictions_overall['3d']} = {stats_by_direction['overall']['3_days']['accuracy']}")
    print(f"5天后准确率：{correct_predictions_overall['5d']}/{valid_predictions_overall['5d']} = {stats_by_direction['overall']['5_days']['accuracy']}")
    
    print("\n" + "-"*60)
    print("【上涨预测统计】")
    print("-"*60)
    print(f"1天后准确率：{correct_predictions_up['1d']}/{valid_predictions_up['1d']} = {stats_by_direction['up']['1_day']['accuracy']}")
    print(f"3天后准确率：{correct_predictions_up['3d']}/{valid_predictions_up['3d']} = {stats_by_direction['up']['3_days']['accuracy']}")
    print(f"5天后准确率：{correct_predictions_up['5d']}/{valid_predictions_up['5d']} = {stats_by_direction['up']['5_days']['accuracy']}")
    
    print("\n" + "-"*60)
    print("【下跌预测统计】")
    print("-"*60)
    print(f"1天后准确率：{correct_predictions_down['1d']}/{valid_predictions_down['1d']} = {stats_by_direction['down']['1_day']['accuracy']}")
    print(f"3天后准确率：{correct_predictions_down['3d']}/{valid_predictions_down['3d']} = {stats_by_direction['down']['3_days']['accuracy']}")
    print(f"5天后准确率：{correct_predictions_down['5d']}/{valid_predictions_down['5d']} = {stats_by_direction['down']['5_days']['accuracy']}")
    
    # 打印按来源分类的统计
    if source_stats_overall:
        print("\n" + "="*60)
        print("📊 按来源分类统计")
        print("="*60)
        
        for source in source_stats_overall.keys():
            print(f"\n【{source}】")
            
            # 总体
            overall = source_stats_overall[source]
            print(f"  总体 - 1天: {overall['1d']['accuracy']} ({overall['1d']['correct']}/{overall['1d']['total']})")
            print(f"        3天: {overall['3d']['accuracy']} ({overall['3d']['correct']}/{overall['3d']['total']})")
            print(f"        5天: {overall['5d']['accuracy']} ({overall['5d']['correct']}/{overall['5d']['total']})")
            
            # 上涨预测
            if source in source_stats_up:
                up = source_stats_up[source]
                print(f"  上涨 - 1天: {up['1d']['accuracy']} ({up['1d']['correct']}/{up['1d']['total']})")
                print(f"        3天: {up['3d']['accuracy']} ({up['3d']['correct']}/{up['3d']['total']})")
                print(f"        5天: {up['5d']['accuracy']} ({up['5d']['correct']}/{up['5d']['total']})")
            
            # 下跌预测
            if source in source_stats_down:
                down = source_stats_down[source]
                print(f"  下跌 - 1天: {down['1d']['accuracy']} ({down['1d']['correct']}/{down['1d']['total']})")
                print(f"        3天: {down['3d']['accuracy']} ({down['3d']['correct']}/{down['3d']['total']})")
                print(f"        5天: {down['5d']['accuracy']} ({down['5d']['correct']}/{down['5d']['total']})")
    
    print("="*60)
    print("\n✅ 验证完成！")