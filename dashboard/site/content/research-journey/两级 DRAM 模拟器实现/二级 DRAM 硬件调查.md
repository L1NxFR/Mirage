---
title: 二级 DRAM 硬件调查
description:
subtitle: ""
tldr:
author:
  - Nan Lin
date: 2026-11-27T10:55:33.999+08:00
lastmod: 2026-11-27T11:15:32+08:00
draft: false
content_lang: zh-CN
tags: []
show_toc: true
weight: 2
---
要求：2 Level of Memory within Single GPU

总结：截止目前没有找到量产化的符合这个要求的产品……

## 相关公开设计

### KAIST：HBM–LPDDR 路线图

KAIST TERA Lab 的路线图提出在定制 HBM base die 中加入 LPDDR 控制器。[路线图，Ver 1.2，2025-05-21][kaist]

| 内存       | 容量         | 带宽     |
| -------- | ---------- | ------ |
| 一级 HBM4  | 36 / 48 GB | 2 TB/s |
| 二级 LPDDR | 未核实        | 未核实    |

