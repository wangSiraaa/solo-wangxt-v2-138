"""挖填量计算软件算例 —— FastAPI 后端。

模块划分：
    models    数据结构（高程点、方案、计算结果）
    tin       限定范围内 TIN（SciPy Delaunay + Shapely 边界裁剪）
    overlay   原地面 / 设计面 TIN 叠加单元
    volume    分片挖、填精确积分（线性面 - 线性面 = 线性差值）
    grid      规则网格（棱柱法/角点法），用于精度对比
    sections  断面（原地面线、设计线、断面挖填面积）
    qc        数据检查：重复点、退化三角片、边界外点、基准不一致
    crs       坐标 / 高程基准校验与 pyproj 转换
    cases     内置软件算例（平面坡地可手算、孔洞、缺测、起伏地形）
"""
