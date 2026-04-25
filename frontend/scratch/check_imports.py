import re
import os

def check_imports(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple regex to find the lucide-react import list
    import_match = re.search(r"import \{([^}]+)\} from 'lucide-react';", content)
    if not import_match:
        print(f"No lucide-react import found in {file_path}")
        return
    
    imports = [i.strip().split(' as ')[0] for i in import_match.group(1).split(',')]
    
    # Find all component usages like <IconName
    usages = re.findall(r"<([A-Z][a-zA-Z0-9]+)", content)
    
    missing = []
    for usage in usages:
        if usage not in imports and usage not in ['div', 'span', 'img', 'video', 'canvas', 'a', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'li', 'button', 'input', 'select', 'textarea', 'label', 'form', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'Fragment', 'PieChart', 'Pie', 'Cell', 'ResponsiveContainer', 'Tooltip', 'Legend', 'AreaChart', 'Area', 'XAxis', 'YAxis', 'CartesianGrid', 'Radar', 'RadarChart', 'PolarGrid', 'PolarAngleAxis', 'PolarRadiusAxis', 'Link', 'Image', 'RechartsTooltip', 'UserIcon', 'PieChartIcon']:
            # Also check if it's imported from somewhere else like next/navigation or next/link
            # For simplicity, just list them and I'll filter
            missing.append(usage)
    
    # Also check icons used as variables like icon: IconName
    variable_usages = re.findall(r"icon: ([A-Z][a-zA-Z0-9]+)", content)
    for usage in variable_usages:
        if usage not in imports and usage not in ['UserIcon']:
            missing.append(usage)

    unique_missing = sorted(list(set(missing)))
    if unique_missing:
        print(f"Potential missing imports in {file_path}: {unique_missing}")
    else:
        print(f"No missing lucide-react imports detected in {file_path}")

check_imports(r"d:\AI_Interviews\interview-new-main\frontend\app\dashboard\page.tsx")
