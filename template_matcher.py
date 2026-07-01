# -*- coding: utf-8 -*-
"""
OpenCV 模板匹配工具模块

提供 find_text() 函数：在源图中查找模板匹配区域，
返回结构化结果（左上角、尺寸、中心点、置信度）。

可被其他脚本 import 调用，也可单独运行测试。
"""

import os
import cv2
import numpy as np


def _imread_unicode(path, flags=cv2.IMREAD_GRAYSCALE):
    """支持中文路径的 imread，文件不存在或为空时返回 None"""
    if not os.path.exists(path):
        return None
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    try:
        return cv2.imdecode(data, flags)
    except Exception:
        return None


def _nms(matches, overlap_thresh=0.3):
    """非极大值抑制：合并重叠的检测框，只保留得分最高的"""
    if not matches:
        return []

    boxes = np.array([[m[0], m[1], m[0] + m[2], m[1] + m[3]] for m in matches], dtype=np.float32)
    scores = np.array([m[4] for m in matches], dtype=np.float32)

    keep = []
    order = scores.argsort()[::-1]

    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break

        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_rest = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / (area_i + area_rest - inter + 1e-8)

        order = order[1:][iou <= overlap_thresh]

    return [matches[i] for i in keep]


def find_text(source_path, template_path, threshold=0.8):
    """
    在源图中查找模板匹配区域，返回结构化结果。

    参数:
        source_path  (str): 源图路径（支持中文）
        template_path(str): 模板图片路径（支持中文）
        threshold    (float): 匹配置信度阈值，默认 0.8

    返回:
        list[dict]: 匹配结果列表，按置信度降序排列。每个元素:
            {
                "左上角": (x, y),       # 模板在源图中的左上角坐标
                "尺寸":   (w, h),       # 匹配区域宽高
                "中心点": (cx, cy),     # 匹配区域中心坐标
                "置信度": float,        # 匹配置信度 (0~1)
            }
            无匹配时返回空列表 []。
    """
    source = _imread_unicode(source_path, cv2.IMREAD_GRAYSCALE)
    template = _imread_unicode(template_path, cv2.IMREAD_GRAYSCALE)

    if source is None:
        raise FileNotFoundError(f"无法读取源图: {source_path}")
    if template is None:
        raise FileNotFoundError(f"无法读取模板: {template_path}")

    h, w = template.shape[:2]

    # 模板匹配
    result = cv2.matchTemplate(source, template, cv2.TM_CCOEFF_NORMED)

    # 筛选超过阈值的匹配
    locations = np.where(result >= threshold)
    raw_matches = []
    for pt in zip(*locations[::-1]):
        score = result[pt[1], pt[0]]
        raw_matches.append((pt[0], pt[1], w, h, float(score)))

    if not raw_matches:
        return []

    # 非极大值抑制去重
    raw_matches = _nms(raw_matches, overlap_thresh=0.3)

    # 组装结构化结果，按置信度降序
    results = []
    for x, y, mw, mh, score in raw_matches:
        results.append({
            "左上角": (int(x), int(y)),
            "尺寸": (int(mw), int(mh)),
            "中心点": (int(x + mw // 2), int(y + mh // 2)),
            "置信度": round(score, 4),
        })

    results.sort(key=lambda r: r["置信度"], reverse=True)
    return results


def draw_results(source_path, results, output_path):
    """
    在源图上标注匹配结果并保存。

    参数:
        source_path (str): 源图路径
        results     (list[dict]): find_text() 的返回值
        output_path (str): 标注图保存路径
    """
    img = _imread_unicode(source_path, cv2.IMREAD_COLOR)
    for r in results:
        x, y = r["左上角"]
        w, h = r["尺寸"]
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
        label = f'{r["置信度"]:.3f}'
        cv2.putText(img, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    ext = os.path.splitext(output_path)[1]
    success, encoded = cv2.imencode(ext, img)
    if success:
        encoded.tofile(output_path)


# ===== 单独运行时的测试入口 =====
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("用法: python template_matcher.py <源图路径> <模板路径> [阈值]")
        sys.exit(1)

    src = sys.argv[1]
    tpl = sys.argv[2]
    thr = float(sys.argv[3]) if len(sys.argv) > 3 else 0.8

    results = find_text(src, tpl, thr)

    if not results:
        print("未找到匹配区域，可尝试降低阈值。")
        sys.exit(0)

    print(f"找到 {len(results)} 个匹配区域:\n")
    for i, r in enumerate(results, 1):
        print(f"  匹配 {i}:")
        print(f"    左上角: {r['左上角']}")
        print(f"    尺寸:   {r['尺寸']}")
        print(f"    中心点: {r['中心点']}")
        print(f"    置信度: {r['置信度']:.4f}\n")
