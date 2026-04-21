"""快速检查 Excel 列含义"""
import pandas as pd, sys
sys.stdout.reconfigure(encoding='utf-8')
DATA = r'D:\Postgraduate\均质化\SJTU-TPMSHX\data\raw_data\20260401-上海电气天然气加热器实验工况.xlsx'

# Read header rows
df_hdr = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, nrows=2)
df = pd.read_excel(DATA, engine='openpyxl', sheet_name='Sheet1', header=None, skiprows=2)

print("=== Header row 0 and 1 for each column ===")
for col in range(min(50, df.shape[1])):
    h0 = df_hdr.iloc[0, col] if col < df_hdr.shape[1] else ''
    h1 = df_hdr.iloc[1, col] if col < df_hdr.shape[1] else ''
    val8 = df.iloc[7, col] if col < df.shape[1] else ''
    print(f"  col {col:2d}: '{h0}' / '{h1}'  → Case8 val = {val8}")
