"""
行情验证器 - 基于实际行情数据验证预测准确率（增量更新模式）
功能：
1. 读取分析结果CSV
2. 检查已有验证结果，跳过已验证的股票
3. 只验证新增的预测（增量更新，补缺失值）
4. 获取每只股票在新闻发布后1天、3天、5天的涨跌幅（基于交易日）
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
import re
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
def get_stock_history_data(stock_code, start_date, end_date, retries=1):
    """
    使用akshare获取股票历史行情（带重试机制）
    返回DataFrame，包含日期和收盘价
    """
    for attempt in range(retries):
        try:
            # 转换日期格式为YYYYMMDD
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")

            symbol = get_stock_symbol(stock_code)
            
            # 使用akshare获取日线数据
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_str,
                end_date=end_str,
                adjust="qfq"
            )            
            if df is None or df.empty:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return None
                        
            # 处理数据
            if 'date' in df.columns and 'close' in df.columns:
                df = df.rename(columns={'date': '日期', 'close': '收盘'})
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                df = df.dropna(subset=['日期'])
                
                if df.empty:
                    return None
                
                df = df.sort_values('日期').reset_index(drop=True)
                return df
            else:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return None
            
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2)
            else:
                print(f"   ⚠️ 获取 {stock_code} 数据失败：{str(e)}")
                return None

# 计算指定交易天数后的涨跌幅（核心修复）
def calculate_return(stock_code, publish_date, trading_days_after):
    """
    计算股票在新闻发布后指定交易天数后的涨跌幅
    基于交易日序号，直接数交易日
    
    参数:
        stock_code: 股票代码
        publish_date: 新闻发布时间
        trading_days_after: 交易天数（1、3、5）
    
    返回:
        涨跌幅百分比，如果数据不足则返回None
    """
    try:
        # 获取从发布日前10天到现在的所有数据（确保有足够数据）
        start_date = publish_date - timedelta(days=20)
        end_date = datetime.now() + timedelta(days=5)
        
        # 获取历史数据
        df = get_stock_history_data(stock_code, start_date, end_date)
        
        if df is None or df.empty:
            return None
        
        # 找到新闻发布日对应的行（找最近的一个交易日）
        publish_date_only = publish_date.date() if hasattr(publish_date, 'date') else publish_date
        
        # 查找发布日当天或之前最近的交易日
        publish_idx = None
        for idx, row in df.iterrows():
            if row['日期'].date() <= publish_date_only:
                publish_idx = idx
            else:
                break
        
        if publish_idx is None:
            print(f"      ⚠️ {stock_code} 找不到发布日 {publish_date_only} 之前的交易日")
            return None
        
        # 计算目标交易日索引（往后数trading_days_after个交易日）
        target_idx = publish_idx + trading_days_after
        
        # 检查是否超出数据范围
        if target_idx >= len(df):
            print(f"      ⏳ {stock_code} 数据不足：需要 {trading_days_after} 个交易日后，当前只有 {len(df)-publish_idx-1} 个")
            return None
        
        # 获取基准价格和目标价格
        base_price = df.iloc[publish_idx]['收盘']
        target_price = df.iloc[target_idx]['收盘']
        
        # 计算涨跌幅
        if base_price == 0:
            return None
        
        return_pct = ((target_price - base_price) / base_price) * 100
        return round(return_pct, 2)
        
    except Exception as e:
        print(f"   ⚠️ 计算 {stock_code} 涨跌幅失败：{str(e)}")
        return None

# 检查收益数据是否有效
def is_valid_return(return_value):
    """检查收益数据是否有效"""
    if return_value is None:
        return False
    if isinstance(return_value, str) and return_value == '':
        return False
    if isinstance(return_value, (int, float)):
        return True
    if isinstance(return_value, str):
        try:
            float(return_value)
            return True
        except ValueError:
            return False
    return False

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

# 读取已验证的结果
def load_existing_results():
    """读取已有的验证结果"""
    if not os.path.exists(OUTPUT_CSV):
        return {}, set()
    
    existing_results = {}
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
        if return_field in row:
            val = row[return_field]
            if val is None or val == '' or (isinstance(val, str) and val.strip() == ''):
                missing_periods.append(period)
    return missing_periods

# 保存验证结果
def save_or_update_results(all_results_dict):
    """保存所有验证结果"""
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
            result['published'] = format_published_date(result['published'])
            
            # 确保数据格式正确
            for period in ['1d', '3d', '5d']:
                return_field = f'return_{period}'
                if return_field in result:
                    val = result[return_field]
                    if val is None or val == '':
                        result[return_field] = ''
                    else:
                        try:
                            result[return_field] = str(float(val))
                        except:
                            result[return_field] = ''
            
            writer.writerow(result)
    
    print(f"✅ 已保存 {len(all_results_dict)} 条验证结果")

# 按来源统计准确率
def calculate_accuracy_by_source(all_results_df):
    """按新闻来源统计预测准确率"""
    if all_results_df.empty:
        return {}, {}, {}
    
    source_stats_overall = {}
    source_stats_up = {}
    source_stats_down = {}
    
    sources = all_results_df['source'].unique()
    
    for source in sources:
        source_data = all_results_df[all_results_df['source'] == source]
        
        overall_stats = {}
        up_stats = {}
        down_stats = {}
        
        for period in ['1d', '3d', '5d']:
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
                overall_stats[f'{period}'] = {'total': 0, 'correct': 0, 'accuracy': 'N/A'}
            
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
                up_stats[f'{period}'] = {'total': 0, 'correct': 0, 'accuracy': 'N/A'}
            
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
                down_stats[f'{period}'] = {'total': 0, 'correct': 0, 'accuracy': 'N/A'}
        
        source_stats_overall[source] = overall_stats
        source_stats_up[source] = up_stats
        source_stats_down[source] = down_stats
    
    return source_stats_overall, source_stats_up, source_stats_down

# 保存统计数据
def save_statistics(stats_overall, stats_by_direction, source_stats_overall, source_stats_up, source_stats_down):
    fieldnames = ['metric', '1_day', '3_days', '5_days']
    
    with open(STATS_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # 总体统计（按方向）
        writer.writerow({'metric': '=== 总体统计（按方向） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for direction, stats in stats_by_direction.items():
            direction_name = {'overall': '总体', 'up': '上涨预测', 'down': '下跌预测'}.get(direction, direction)
            writer.writerow({'metric': f'【{direction_name}】', '1_day': '', '3_days': '', '5_days': ''})
            
            writer.writerow({
                'metric': '  预测准确率',
                '1_day': stats['1_day']['accuracy'],
                '3_days': stats['3_days']['accuracy'],
                '5_days': stats['5_days']['accuracy']
            })
            
            writer.writerow({
                'metric': '  有效预测数',
                '1_day': str(stats['1_day']['total']),
                '3_days': str(stats['3_days']['total']),
                '5_days': str(stats['5_days']['total'])
            })
            
            writer.writerow({
                'metric': '  正确预测数',
                '1_day': str(stats['1_day']['correct']),
                '3_days': str(stats['3_days']['correct']),
                '5_days': str(stats['5_days']['correct'])
            })
            
            writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        
        writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        writer.writerow({'metric': '=== 总体统计（总体指标） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for metric, values in stats_overall.items():
            row = {'metric': metric}
            row.update(values)
            writer.writerow(row)
        
        writer.writerow({'metric': '', '1_day': '', '3_days': '', '5_days': ''})
        writer.writerow({'metric': '=== 按来源分类（总体） ===', '1_day': '', '3_days': '', '5_days': ''})
        
        for source, periods in source_stats_overall.items():
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

# 测试数据接口
def test_api():
    """测试数据接口是否正常"""
    print("🔍 测试数据接口...")
    test_date = datetime.now() - timedelta(days=1)
    df = get_stock_history_data('600519', test_date - timedelta(days=5), test_date, retries=1)
    if df is not None and not df.empty:
        print(f"✅ 数据接口正常，获取到 {len(df)} 条数据")
        return True
    else:
        print("❌ 数据接口异常，请检查网络或akshare版本")
        print("建议执行: pip install --upgrade akshare")
        return False

# 主函数
if __name__ == "__main__":
    print("🚀 开始行情验证（基于交易日序号）...\n")
    
    # 测试数据接口
    if not test_api():
        print("\n⚠️ 数据接口测试失败")
        response = input("是否继续？(y/n): ")
        if response.lower() != 'y':
            exit()
    
    # 1. 加载数据
    analysis_results = load_analysis_results()
    news_database = load_news_database()
    
    if not analysis_results:
        print("❌ 没有可验证的分析结果")
        exit()
    
    # 2. 加载已有验证结果
    existing_results, verified_keys = load_existing_results()
    print(f"📊 已有验证结果：{len(existing_results)} 条\n")
    
    # 3. 准备存储所有结果
    all_results_dict = existing_results.copy()
    
    # 统计变量
    total_predictions = 0
    correct_predictions_overall = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions_overall = {'1d': 0, '3d': 0, '5d': 0}
    
    correct_predictions_up = {'1d': 0, '3d': 0, '5d': 0}
    valid_predictions_up = {'1d': 0, '3d': 0, '5d': 0}
    
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
        
        if news_id not in news_database:
            print(f"   ⚠️ 未找到新闻 {news_id} 的基础信息")
            continue
        
        formatted_published = format_published_date(published)
        source = news_database[news_id].get('source', '未知来源')
        
        publish_date = parse_published_date(published)
        if not publish_date:
            print(f"   ⚠️ 无法解析发布时间")
            continue
        
        print(f"   📅 新闻时间: {publish_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
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
                
                verify_key = f"{news_id}_{stock_code}_{pred_type}"
                
                # 检查是否已存在
                if verify_key in all_results_dict:
                    existing_row = all_results_dict[verify_key]
                    missing_periods = check_missing_returns(existing_row)
                    
                    if missing_periods:
                        print(f"   🔄 更新预测：{stock_code} ({pred_type}) - 缺失 {', '.join(missing_periods)}")
                        
                        updated = False
                        for period in missing_periods:
                            days = 1 if period == '1d' else 3 if period == '3d' else 5
                            return_pct = calculate_return(stock_code, publish_date, days)
                            
                            if return_pct is not None:
                                existing_row[f'return_{period}'] = return_pct
                                if pred_type == 'up':
                                    is_correct = 1 if return_pct > 0 else 0
                                else:
                                    is_correct = 1 if return_pct < 0 else 0
                                existing_row[f'is_correct_{period}'] = is_correct
                                updated = True
                                print(f"      ✅ 补全 {period}: {return_pct}%")
                                
                                # 更新统计
                                valid_predictions_overall[period] += 1
                                correct_predictions_overall[period] += is_correct
                                if pred_type == 'up':
                                    valid_predictions_up[period] += 1
                                    correct_predictions_up[period] += is_correct
                                else:
                                    valid_predictions_down[period] += 1
                                    correct_predictions_down[period] += is_correct
                            else:
                                print(f"      ⏳ {period} 数据暂不可用")
                        
                        if updated:
                            all_results_dict[verify_key] = existing_row
                            updated_count += 1
                    else:
                        if verify_key not in verified_keys:
                            print(f"   📊 已有完整数据：{stock_code} ({pred_type})")
                            for period in ['1d', '3d', '5d']:
                                return_val = existing_row.get(f'return_{period}')
                                if is_valid_return(return_val):
                                    valid_predictions_overall[period] += 1
                                    correct_predictions_overall[period] += int(existing_row.get(f'is_correct_{period}', 0))
                                    if pred_type == 'up':
                                        valid_predictions_up[period] += 1
                                        correct_predictions_up[period] += int(existing_row.get(f'is_correct_{period}', 0))
                                    else:
                                        valid_predictions_down[period] += 1
                                        correct_predictions_down[period] += int(existing_row.get(f'is_correct_{period}', 0))
                            skipped_complete_count += 1
                else:
                    # 新增预测
                    print(f"   🆕 新增验证：{stock_code} ({pred_type})")
                    
                    return_1d = calculate_return(stock_code, publish_date, 1)
                    return_3d = calculate_return(stock_code, publish_date, 3)
                    return_5d = calculate_return(stock_code, publish_date, 5)
                    
                    # 显示获取结果
                    print(f"      1天后: {return_1d}%" if return_1d else "      1天后: 数据不足")
                    print(f"      3天后: {return_3d}%" if return_3d else "      3天后: 数据不足")
                    print(f"      5天后: {return_5d}%" if return_5d else "      5天后: 数据不足")
                    
                    # 判断正确性
                    if pred_type == 'up':
                        is_correct_1d = 1 if return_1d is not None and return_1d > 0 else 0
                        is_correct_3d = 1 if return_3d is not None and return_3d > 0 else 0
                        is_correct_5d = 1 if return_5d is not None and return_5d > 0 else 0
                    else:
                        is_correct_1d = 1 if return_1d is not None and return_1d < 0 else 0
                        is_correct_3d = 1 if return_3d is not None and return_3d < 0 else 0
                        is_correct_5d = 1 if return_5d is not None and return_5d < 0 else 0
                    
                    # 统计有效数据
                    for period, ret, is_correct in [('1d', return_1d, is_correct_1d), 
                                                     ('3d', return_3d, is_correct_3d),
                                                     ('5d', return_5d, is_correct_5d)]:
                        if ret is not None:
                            valid_predictions_overall[period] += 1
                            correct_predictions_overall[period] += is_correct
                            if pred_type == 'up':
                                valid_predictions_up[period] += 1
                                correct_predictions_up[period] += is_correct
                            else:
                                valid_predictions_down[period] += 1
                                correct_predictions_down[period] += is_correct
                    
                    total_predictions += 1
                    new_added_count += 1
                    
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
                    
                    time.sleep(0.5)
    
    # 4. 保存所有结果
    if all_results_dict:
        save_or_update_results(all_results_dict)
    
    # 5. 准备统计数据
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
    
    # 按来源统计
    if all_results_dict:
        all_results_list = list(all_results_dict.values())
        all_results_df = pd.DataFrame(all_results_list)
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
            
            overall = source_stats_overall[source]
            print(f"  总体 - 1天: {overall['1d']['accuracy']} ({overall['1d']['correct']}/{overall['1d']['total']})")
            print(f"        3天: {overall['3d']['accuracy']} ({overall['3d']['correct']}/{overall['3d']['total']})")
            print(f"        5天: {overall['5d']['accuracy']} ({overall['5d']['correct']}/{overall['5d']['total']})")
            
            if source in source_stats_up:
                up = source_stats_up[source]
                print(f"  上涨 - 1天: {up['1d']['accuracy']} ({up['1d']['correct']}/{up['1d']['total']})")
                print(f"        3天: {up['3d']['accuracy']} ({up['3d']['correct']}/{up['3d']['total']})")
                print(f"        5天: {up['5d']['accuracy']} ({up['5d']['correct']}/{up['5d']['total']})")
            
            if source in source_stats_down:
                down = source_stats_down[source]
                print(f"  下跌 - 1天: {down['1d']['accuracy']} ({down['1d']['correct']}/{down['1d']['total']})")
                print(f"        3天: {down['3d']['accuracy']} ({down['3d']['correct']}/{down['3d']['total']})")
                print(f"        5天: {down['5d']['accuracy']} ({down['5d']['correct']}/{down['5d']['total']})")
    
    print("="*60)
    print("\n✅ 验证完成！")