# Headless Browser Detection: 1000-URL Comparative Analysis

**Date**: 2026-03-12
**Job**: `job_20260312_003014`
**URLs tested**: 965 (from top-1000 Tranco list)
**Modes**: headless, headful (baseline), headless-shell
**Chrome**: headful/headless = 144.0, headless-shell = chromium-headless-shell

---

## 1. Executive Summary

We tested 965 URLs from the Tranco top-1000 list across three Chrome browser modes — standard **headless**, **headful** (baseline), and **headless-shell** (stripped binary) — to measure rendering fidelity differences. Each non-headful mode was compared pairwise against headful.

| Metric                  | Headless    | Headless-Shell |
|-------------------------|-------------|----------------|
| Identical to headful    | 30.6% (295) | 24.1% (233)    |
| Mean severity           | 9.83        | 21.61          |
| Severity > 100          | 0.8% (8)    | 4.4% (42)      |
| Screenshot diff > 50%   | 2.3% (22)   | 5.0% (48)      |
| Errored (headless side) | 2.8% (27)   | 4.8% (46)      |

**Only 22.8% of sites (220) render identically in both headless modes.** Standard headless is significantly more compatible than headless-shell, but headless-shell uses ~50% less memory.

---

## 2. Methodology

### Infrastructure
- **Docker containers**: one per mode, resource-limited to 4 CPUs and 8 GB RAM, 8 GB shared memory
- **Execution**: sequential (one mode at a time) to eliminate resource contention
- **Chrome version**: system Chrome (`channel="chrome"`) for headless/headful, `chromium-headless-shell` for headless-shell

### Anti-Detection Measures (all modes)
- `--disable-blink-features=AutomationControlled`
- `navigator.webdriver` patched to `undefined`
- Matching User-Agent: `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36`

### Collection Parameters
- Page timeout: 10 seconds
- Settle time: 2 seconds post-load
- Wait strategy: `domcontentloaded`
- Viewport: 1280x720

### Metrics Collected
- Full-page screenshots (PNG)
- DOM element counts (total + per-tag)
- DOM serialized size
- Visible text content length
- Network requests (count, types, HAR)
- Resource Timing API (transfer bytes, decoded bytes, resources by initiator)
- Navigation Timing API (DNS, TTFB, DOM interactive, load event, etc.)
- Page dimensions (document height/width)
- Process memory (RSS, USS) and CPU time
- Page title, final URL, console errors

---

## 3. Comprehensive 3-Mode Statistics

868 URLs valid in all 3 modes (no errors). All stats computed on this matched set unless noted otherwise.

### Resource Metrics

| Metric                              | Stat       |         headful |        headless |  headless-shell |
|-------------------------------------|------------|-----------------|-----------------|-----------------|
| **CPU Time before SS (s)** (n=868)  | avg        |            1.98 |            1.97 |            1.55 |
|                                     | std        |            1.54 |            1.81 |            1.33 |
|                                     | min        |            0.16 |            0.13 |            0.03 |
|                                     | p25        |            0.88 |            0.83 |            0.56 |
|                                     | median     |            1.62 |            1.56 |            1.23 |
|                                     | p75        |            2.65 |            2.62 |            2.23 |
|                                     | max        |           11.39 |           29.52 |            9.22 |
|                                     | **ratio**  |       **1.00x** |       **1.01x** |       **1.28x** |
|                                     |            |                 |                 |                 |
| **CPU Time incl. SS (s)** (n=868)   | avg        |            2.15 |            2.22 |            1.70 |
|                                     | std        |            1.77 |            3.46 |            1.51 |
|                                     | min        |            0.18 |            0.15 |            0.05 |
|                                     | p25        |            0.98 |            0.92 |            0.65 |
|                                     | median     |            1.73 |            1.69 |            1.32 |
|                                     | p75        |            2.78 |            2.76 |            2.34 |
|                                     | max        |           16.16 |           88.66 |           15.42 |
|                                     | **ratio**  |       **1.00x** |       **0.97x** |       **1.27x** |
|                                     |            |                 |                 |                 |
| **CPU SS delta (s)** (n=868)        | avg        |            0.17 |            0.25 |            0.15 |
|                                     | std        |            0.45 |            2.08 |            0.38 |
|                                     | min        |            0.01 |           -0.00 |            0.00 |
|                                     | p25        |            0.05 |            0.04 |            0.04 |
|                                     | median     |            0.08 |            0.08 |            0.07 |
|                                     | p75        |            0.14 |            0.15 |            0.13 |
|                                     | max        |            7.34 |           59.14 |            6.20 |
|                                     | **ratio**  |       **1.00x** |       **0.68x** |       **1.16x** |
|                                     |            |                 |                 |                 |
| **Peak RSS before SS (MB)** (n=868) | avg        |            1130 |            1065 |             582 |
|                                     | std        |             351 |             348 |             152 |
|                                     | min        |             779 |             709 |             367 |
|                                     | p25        |             907 |             844 |             483 |
|                                     | median     |            1032 |             976 |             559 |
|                                     | p75        |            1223 |            1161 |             658 |
|                                     | max        |            3553 |            3550 |            2053 |
|                                     | **ratio**  |       **1.00x** |       **1.06x** |       **1.94x** |
|                                     |            |                 |                 |                 |
| **RSS after SS (MB)** (n=868)       | avg        |            1151 |            1090 |             591 |
|                                     | std        |             385 |             412 |             147 |
|                                     | min        |             786 |             721 |             378 |
|                                     | p25        |             915 |             851 |             490 |
|                                     | median     |            1043 |             986 |             566 |
|                                     | p75        |            1235 |            1173 |             668 |
|                                     | max        |            4624 |            6194 |            1404 |
|                                     | **ratio**  |       **1.00x** |       **1.06x** |       **1.95x** |
|                                     |            |                 |                 |                 |
| **RSS SS delta (MB)** (n=868)       | avg        |           20.15 |           24.60 |            9.52 |
|                                     | std        |           74.34 |          166.59 |           30.02 |
|                                     | min        |         -220.20 |         -209.34 |         -648.52 |
|                                     | p25        |            3.41 |            3.94 |            2.88 |
|                                     | median     |            8.31 |            9.51 |            8.85 |
|                                     | p75        |           12.54 |           13.50 |           10.94 |
|                                     | max        |         1071.10 |         4509.38 |          203.23 |
|                                     | **ratio**  |       **1.00x** |       **0.82x** |       **2.12x** |
|                                     |            |                 |                 |                 |
| **Peak USS before SS (MB)** (n=868) | avg        |             319 |             297 |             228 |
|                                     | std        |             130 |             127 |             126 |
|                                     | min        |             159 |             137 |              78 |
|                                     | p25        |             233 |             213 |             150 |
|                                     | median     |             291 |             270 |             205 |
|                                     | p75        |             374 |             354 |             285 |
|                                     | max        |            1143 |            1000 |            1718 |
|                                     | **ratio**  |       **1.00x** |       **1.07x** |       **1.40x** |
|                                     |            |                 |                 |                 |
| **USS after SS (MB)** (n=868)       | avg        |             327 |             305 |             234 |
|                                     | std        |             133 |             132 |             119 |
|                                     | min        |             165 |             142 |              85 |
|                                     | p25        |             239 |             218 |             156 |
|                                     | median     |             294 |             274 |             210 |
|                                     | p75        |             379 |             358 |             288 |
|                                     | max        |            1039 |            1058 |             901 |
|                                     | **ratio**  |       **1.00x** |       **1.07x** |       **1.39x** |
|                                     |            |                 |                 |                 |
| **USS SS delta (MB)** (n=868)       | avg        |            7.38 |            7.70 |            5.71 |
|                                     | std        |           22.01 |           30.12 |           32.81 |
|                                     | min        |         -191.57 |         -170.75 |         -817.03 |
|                                     | p25        |            1.22 |            0.43 |            0.39 |
|                                     | median     |            3.80 |            3.79 |            6.30 |
|                                     | p75        |            8.77 |            8.41 |            8.25 |
|                                     | max        |          270.19 |          654.41 |          196.06 |
|                                     | **ratio**  |       **1.00x** |       **0.96x** |       **1.29x** |
|                                     |            |                 |                 |                 |

### DOM & Content Metrics

| Metric                                  | Stat       |         headful |        headless |  headless-shell |
|-----------------------------------------|------------|-----------------|-----------------|-----------------|
| **DOM Element Count** (n=868)           | avg        |            1676 |            1674 |            1603 |
|                                         | std        |            1710 |            1694 |            1679 |
|                                         | min        |               3 |               3 |               3 |
|                                         | p25        |             504 |             514 |             413 |
|                                         | median     |            1234 |            1234 |            1171 |
|                                         | p75        |            2268 |            2250 |            2186 |
|                                         | max        |           11628 |           11628 |           12021 |
|                                         | **ratio**  |       **1.00x** |       **1.00x** |       **1.05x** |
|                                         |            |                 |                 |                 |
| **DOM Size (bytes)** (n=868)            | avg        |          519845 |          522698 |          497291 |
|                                         | std        |          787593 |          799254 |          776089 |
|                                         | min        |              39 |              39 |              39 |
|                                         | p25        |           92083 |           93779 |           73689 |
|                                         | median     |          317994 |          320862 |          286248 |
|                                         | p75        |          679238 |          675758 |          640331 |
|                                         | max        |        13437545 |        13954358 |        13397688 |
|                                         | **ratio**  |       **1.00x** |       **0.99x** |       **1.05x** |
|                                         |            |                 |                 |                 |
| **Visible Text Length** (n=868)         | avg        |            5945 |            5972 |            5811 |
|                                         | std        |            7666 |            7520 |            7726 |
|                                         | min        |               0 |               0 |               0 |
|                                         | p25        |            1705 |            1718 |            1387 |
|                                         | median     |            3965 |            4023 |            3793 |
|                                         | p75        |            7347 |            7393 |            7171 |
|                                         | max        |           96851 |           87652 |           97016 |
|                                         | **ratio**  |       **1.00x** |       **1.00x** |       **1.02x** |
|                                         |            |                 |                 |                 |
| **Unique Tag Count** (n=868)            | avg        |              34 |              34 |              34 |
|                                         | std        |              14 |              14 |              14 |
|                                         | min        |               3 |               3 |               3 |
|                                         | p25        |              27 |              27 |              26 |
|                                         | median     |              36 |              36 |              35 |
|                                         | p75        |              42 |              42 |              42 |
|                                         | max        |             143 |             138 |             142 |
|                                         | **ratio**  |       **1.00x** |       **1.00x** |       **1.02x** |
|                                         |            |                 |                 |                 |
| **Structural Elements Present** (n=868) | avg        |            4.09 |            4.10 |            4.00 |
|                                         | std        |            2.37 |            2.38 |            2.43 |
|                                         | min        |            0.00 |            0.00 |            0.00 |
|                                         | p25        |            2.00 |            2.00 |            2.00 |
|                                         | median     |            5.00 |            5.00 |            4.00 |
|                                         | p75        |            6.00 |            6.00 |            6.00 |
|                                         | max        |            9.00 |            9.00 |            9.00 |
|                                         | **ratio**  |       **1.00x** |       **1.00x** |       **1.02x** |
|                                         |            |                 |                 |                 |

### Network & Page Metrics

| Metric                                | Stat       |         headful |        headless |  headless-shell |
|---------------------------------------|------------|-----------------|-----------------|-----------------|
| **Network Requests** (n=868)          | avg        |             117 |             117 |             112 |
|                                       | std        |             101 |             101 |              98 |
|                                       | min        |               1 |               1 |               1 |
|                                       | p25        |              42 |              43 |              38 |
|                                       | median     |              95 |              95 |              90 |
|                                       | p75        |             168 |             168 |             166 |
|                                       | max        |             724 |             728 |             668 |
|                                       | **ratio**  |       **1.00x** |       **1.00x** |       **1.04x** |
|                                       |            |                 |                 |                 |
| **Request Type Count** (n=868)        | avg        |            7.35 |            7.37 |            6.97 |
|                                       | std        |            2.21 |            2.20 |            2.32 |
|                                       | min        |               1 |               1 |               1 |
|                                       | p25        |               7 |               7 |               6 |
|                                       | median     |               8 |               8 |               8 |
|                                       | p75        |               9 |               9 |               9 |
|                                       | max        |              11 |              11 |              11 |
|                                       | **ratio**  |       **1.00x** |       **1.00x** |       **1.06x** |
|                                       |            |                 |                 |                 |
| **HTTP Status** (n=868)              | avg        |             212 |             213 |             216 |
|                                       | std        |              54 |              54 |              61 |
|                                       | min        |               0 |               0 |               0 |
|                                       | p25        |             200 |             200 |             200 |
|                                       | median     |             200 |             200 |             200 |
|                                       | p75        |             200 |             200 |             200 |
|                                       | max        |             520 |             520 |             520 |
|                                       | **ratio**  |       **1.00x** |       **1.00x** |       **0.98x** |
|                                       |            |                 |                 |                 |
| **Console Error Count** (n=868)       | avg        |            1.32 |            1.32 |            1.14 |
|                                       | std        |            2.73 |            2.72 |            2.55 |
|                                       | min        |               0 |               0 |               0 |
|                                       | p25        |               0 |               0 |               0 |
|                                       | median     |               0 |               0 |               0 |
|                                       | p75        |               2 |               2 |               1 |
|                                       | max        |              20 |              20 |              20 |
|                                       | **ratio**  |       **1.00x** |       **1.00x** |       **1.16x** |
|                                       |            |                 |                 |                 |

### Resource Timing Metrics

| Metric                                    | Stat       |         headful |        headless |  headless-shell |
|-------------------------------------------|------------|-----------------|-----------------|-----------------|
| **Resource Count** (n=868)                | avg        |              91 |              91 |              87 |
|                                           | std        |              72 |              72 |              72 |
|                                           | min        |               0 |               0 |               0 |
|                                           | p25        |              34 |              34 |              28 |
|                                           | median     |              78 |              78 |              73 |
|                                           | p75        |             135 |             133 |             134 |
|                                           | max        |             509 |             513 |             505 |
|                                           | **ratio**  |       **1.00x** |       **1.00x** |       **1.04x** |
|                                           |            |                 |                 |                 |
| **Total Transfer Bytes** (n=868)          | avg        |         1667596 |         1679738 |         1689364 |
|                                           | std        |         3727190 |         3753189 |         3696085 |
|                                           | min        |               0 |               0 |               0 |
|                                           | p25        |          160214 |          159713 |          101742 |
|                                           | median     |          701818 |          716567 |          677852 |
|                                           | p75        |         1932289 |         1972558 |         2074382 |
|                                           | max        |        52469884 |        52469284 |        52457492 |
|                                           | **ratio**  |       **1.00x** |       **0.99x** |       **0.99x** |
|                                           |            |                 |                 |                 |
| **Total Decoded Bytes** (n=868)           | avg        |         3341804 |         3343043 |         3254257 |
|                                           | std        |         4932051 |         4908778 |         4882919 |
|                                           | min        |               0 |               0 |               0 |
|                                           | p25        |          387953 |          406041 |          274726 |
|                                           | median     |         1855757 |         1864270 |         1715032 |
|                                           | p75        |         4543619 |         4653169 |         4500694 |
|                                           | max        |        52683955 |        52900834 |        52455498 |
|                                           | **ratio**  |       **1.00x** |       **1.00x** |       **1.03x** |
|                                           |            |                 |                 |                 |

### Navigation Timing Metrics

| Metric                                        | Stat       |         headful |        headless |  headless-shell |
|-----------------------------------------------|------------|-----------------|-----------------|-----------------|
| **DNS (ms)** (n=790)                          | avg        |           98.7  |          101.5  |          129.4  |
|                                               | std        |          121.1  |          147.8  |          156.1  |
|                                               | min        |            3.7  |            3.5  |            0.7  |
|                                               | p25        |           10.0  |           10.0  |           28.7  |
|                                               | median     |           60.2  |           59.7  |          100.2  |
|                                               | p75        |          137.6  |          128.9  |          171.5  |
|                                               | max        |         1000.7  |         2069.4  |         1965.9  |
|                                               | **ratio**  |       **1.00x** |       **0.97x** |       **0.76x** |
|                                               |            |                 |                 |                 |
| **Connect (ms)** (n=792)                      | avg        |          128.5  |          131.0  |          160.7  |
|                                               | std        |          177.7  |          195.6  |          215.7  |
|                                               | min        |            4.6  |            4.4  |            4.2  |
|                                               | p25        |           12.7  |           12.7  |           14.8  |
|                                               | median     |           44.7  |           33.0  |           70.1  |
|                                               | p75        |          169.9  |          155.6  |          209.9  |
|                                               | max        |         1275.1  |         2248.2  |         2666.3  |
|                                               | **ratio**  |       **1.00x** |       **0.98x** |       **0.80x** |
|                                               |            |                 |                 |                 |
| **TTFB (ms)** (n=868)                         | avg        |          573.0  |          576.6  |          649.5  |
|                                               | std        |          581.4  |          589.0  |          733.0  |
|                                               | min        |           21.6  |           21.6  |           25.5  |
|                                               | p25        |          248.9  |          241.0  |          318.1  |
|                                               | median     |          427.0  |          432.9  |          500.9  |
|                                               | p75        |          725.5  |          708.4  |          756.6  |
|                                               | max        |         7237.3  |         5866.4  |         9310.2  |
|                                               | **ratio**  |       **1.00x** |       **0.99x** |       **0.88x** |
|                                               |            |                 |                 |                 |
| **Response (ms)** (n=866)                     | avg        |          100.9  |          108.4  |          114.8  |
|                                               | std        |          200.8  |          263.3  |          222.3  |
|                                               | min        |            0.1  |            0.2  |            0.2  |
|                                               | p25        |            0.8  |            0.8  |            0.8  |
|                                               | median     |           10.1  |            9.9  |            7.6  |
|                                               | p75        |          112.3  |          120.6  |          144.3  |
|                                               | max        |         1765.7  |         5227.4  |         2307.3  |
|                                               | **ratio**  |       **1.00x** |       **0.93x** |       **0.88x** |
|                                               |            |                 |                 |                 |
| **DOM Interactive (ms)** (n=855)              | avg        |         1165.2  |         1160.0  |         1233.8  |
|                                               | std        |         1182.8  |         1165.5  |         1189.6  |
|                                               | min        |           32.8  |           30.6  |           29.8  |
|                                               | p25        |          484.9  |          483.3  |          551.2  |
|                                               | median     |          863.8  |          836.1  |          915.5  |
|                                               | p75        |         1392.6  |         1395.3  |         1403.7  |
|                                               | max        |        11679.3  |        10173.9  |        10210.3  |
|                                               | **ratio**  |       **1.00x** |       **1.00x** |       **0.94x** |
|                                               |            |                 |                 |                 |
| **DOM Content Loaded (ms)** (n=853)           | avg        |         1309.8  |         1310.1  |         1373.6  |
|                                               | std        |         1252.8  |         1224.8  |         1266.1  |
|                                               | min        |           32.8  |           30.7  |           29.8  |
|                                               | p25        |          566.1  |          577.1  |          619.6  |
|                                               | median     |          991.4  |          985.1  |         1011.4  |
|                                               | p75        |         1570.2  |         1566.9  |         1654.0  |
|                                               | max        |        11733.3  |        10717.9  |        10832.6  |
|                                               | **ratio**  |       **1.00x** |       **1.00x** |       **0.95x** |
|                                               |            |                 |                 |                 |
| **DOM Complete (ms)** (n=606)                 | avg        |         1646.1  |         1651.2  |         1684.3  |
|                                               | std        |         1111.4  |         1115.7  |         1176.6  |
|                                               | min        |           32.9  |           30.9  |           30.0  |
|                                               | p25        |          815.9  |          834.6  |          821.2  |
|                                               | median     |         1462.4  |         1464.0  |         1522.9  |
|                                               | p75        |         2247.0  |         2283.7  |         2271.1  |
|                                               | max        |         7559.7  |         7561.8  |         8670.5  |
|                                               | **ratio**  |       **1.00x** |       **1.00x** |       **0.98x** |
|                                               |            |                 |                 |                 |
| **Load Event (ms)** (n=605)                   | avg        |         1649.0  |         1653.2  |         1686.0  |
|                                               | std        |         1113.1  |         1117.6  |         1178.5  |
|                                               | min        |           32.9  |           30.9  |           30.0  |
|                                               | p25        |          815.8  |          833.5  |          820.2  |
|                                               | median     |         1470.9  |         1464.7  |         1520.2  |
|                                               | p75        |         2248.4  |         2286.4  |         2278.8  |
|                                               | max        |         7559.7  |         7561.8  |         8671.4  |
|                                               | **ratio**  |       **1.00x** |       **1.00x** |       **0.98x** |
|                                               |            |                 |                 |                 |

### Page Dimensions

| Metric                              | Stat       |         headful |        headless |  headless-shell |
|-------------------------------------|------------|-----------------|-----------------|-----------------|
| **Document Height (px)** (n=868)    | avg        |            6130 |            6135 |            6021 |
|                                     | std        |            6364 |            6340 |            6395 |
|                                     | min        |             705 |             720 |             720 |
|                                     | p25        |            2065 |            2139 |            1729 |
|                                     | median     |            4838 |            4830 |            4790 |
|                                     | p75        |            7687 |            7697 |            7618 |
|                                     | max        |           73422 |           73422 |           73354 |
|                                     | **ratio**  |       **1.00x** |       **1.00x** |       **1.02x** |
|                                     |            |                 |                 |                 |
| **Document Width (px)** (n=868)     | avg        |            1283 |            1294 |            1294 |
|                                     | std        |             245 |             244 |             244 |
|                                     | min        |            1265 |            1265 |            1265 |
|                                     | p25        |            1265 |            1280 |            1280 |
|                                     | median     |            1265 |            1280 |            1280 |
|                                     | p75        |            1280 |            1280 |            1280 |
|                                     | max        |            8308 |            8315 |            8315 |
|                                     | **ratio**  |       **1.00x** |       **0.99x** |       **0.99x** |
|                                     |            |                 |                 |                 |

---

## 4. Overhead Ratios Summary

Higher ratio = headful uses more of that resource (ratio > 1 means headful is heavier).

| Metric                         |      HF / HL |      HF / HS |      HL / HS |   n |
|--------------------------------|--------------|--------------|--------------|-----|
| CPU Time before SS (s)         |        1.01x |        1.28x |        1.27x | 868 |
| CPU Time incl. SS (s)          |        0.97x |        1.27x |        1.31x | 868 |
| CPU SS delta (s)               |        0.68x |        1.16x |        1.72x | 868 |
| Peak RSS before SS (MB)        |        1.06x |        1.94x |        1.83x | 868 |
| RSS after SS (MB)              |        1.06x |        1.95x |        1.84x | 868 |
| RSS SS delta (MB)              |        0.82x |        2.12x |        2.58x | 868 |
| Peak USS before SS (MB)        |        1.07x |        1.40x |        1.30x | 868 |
| USS after SS (MB)              |        1.07x |        1.39x |        1.30x | 868 |
| USS SS delta (MB)              |        0.96x |        1.29x |        1.35x | 868 |
| DOM Element Count              |        1.00x |        1.05x |        1.04x | 868 |
| DOM Size (bytes)               |        0.99x |        1.05x |        1.05x | 868 |
| Visible Text Length            |        1.00x |        1.02x |        1.03x | 868 |
| Unique Tag Count               |        1.00x |        1.02x |        1.02x | 868 |
| Structural Elements Present    |        1.00x |        1.02x |        1.02x | 868 |
| Network Requests               |        1.00x |        1.04x |        1.04x | 868 |
| Request Type Count             |        1.00x |        1.06x |        1.06x | 868 |
| HTTP Status                    |        1.00x |        0.98x |        0.98x | 868 |
| Console Error Count            |        1.00x |        1.16x |        1.16x | 868 |
| Resource Count                 |        1.00x |        1.04x |        1.04x | 868 |
| Total Transfer Bytes           |        0.99x |        0.99x |        0.99x | 868 |
| Total Decoded Bytes            |        1.00x |        1.03x |        1.03x | 868 |
| DNS (ms)                       |        0.97x |        0.76x |        0.78x | 790 |
| Connect (ms)                   |        0.98x |        0.80x |        0.82x | 792 |
| TTFB (ms)                      |        0.99x |        0.88x |        0.89x | 868 |
| Response (ms)                  |        0.93x |        0.88x |        0.94x | 866 |
| DOM Interactive (ms)           |        1.00x |        0.94x |        0.94x | 855 |
| DOM Content Loaded (ms)        |        1.00x |        0.95x |        0.95x | 853 |
| DOM Complete (ms)              |        1.00x |        0.98x |        0.98x | 606 |
| Load Event (ms)                |        1.00x |        0.98x |        0.98x | 605 |
| Document Height                |        1.00x |        1.02x |        1.02x | 868 |
| Document Width                 |        0.99x |        0.99x |        1.00x | 868 |

---

## 5. Rendering Fidelity

### Diff Type Breakdown

| Category         | Headless     | Headless-Shell | Total |
|------------------|--------------|----------------|-------|
| layout_diff      | 604 (62.6%)  | 605 (62.7%)    | 1,209 |
| identical        | 295 (30.6%)  | 233 (24.1%)    | 528   |
| missing_content  | 22 (2.3%)    | 54 (5.6%)      | 76    |
| both_errored     | 26 (2.7%)    | 22 (2.3%)      | 48    |
| headless_errored | 1 (0.1%)     | 24 (2.5%)      | 25    |
| redirect_diff    | 8 (0.8%)     | 13 (1.3%)      | 21    |
| dom_diff         | 8 (0.8%)     | 7 (0.7%)       | 15    |
| headful_errored  | 1 (0.1%)     | 5 (0.5%)       | 6     |
| title_diff       | 0 (0.0%)     | 2 (0.2%)       | 2     |

Headless-shell has **2.5x more `missing_content`** (54 vs 22) and **24x more `headless_errored`** (24 vs 1).

### Severity Distribution

| Bucket        | Headless     | Headless-Shell |
|---------------|--------------|----------------|
| = 0 (perfect) | 101 (10.5%) | 75 (7.8%)      |
| 0–10          | 641 (66.4%)  | 572 (59.3%)    |
| 10–25         | 127 (13.2%)  | 141 (14.6%)    |
| 25–50         | 67 (6.9%)    | 80 (8.3%)      |
| 50–75         | 14 (1.5%)    | 20 (2.1%)      |
| 75–100        | 7 (0.7%)     | 35 (3.6%)      |
| > 100         | 8 (0.8%)     | 42 (4.4%)      |

| Percentile | Headless | Headless-Shell |
|------------|----------|----------------|
| Median     | 3.71     | 5.56           |
| P75        | 9.11     | 16.14          |
| P90        | 24.64    | 49.78          |
| P95        | 37.54    | 100.00         |
| Max        | 249.64   | 268.77         |

### Error Analysis

| Error Type           | Headless  | Headless-Shell |
|----------------------|-----------|----------------|
| Headless-side errors | 27 (2.8%) | 46 (4.8%)      |
| Headful-side errors  | 27 (2.8%) | 27 (2.8%)      |

Most common errors: "JS evaluation failed" (27), "Mode timed out after 60s" (24), various certificate/HTTP errors.

---

## 6. Screenshot Differences

| Threshold       | Headless     | Headless-Shell |
|-----------------|--------------|----------------|
| Any diff (> 0%) | 827 (85.7%) | 853 (88.4%)    |
| > 5%            | 630 (65.3%)  | 669 (69.3%)    |
| > 10%           | 358 (37.1%)  | 415 (43.0%)    |
| > 25%           | 97 (10.1%)   | 132 (13.7%)    |
| > 50%           | 22 (2.3%)    | 48 (5.0%)      |

Mean screenshot diff (excluding zeros): headless 12.83%, headless-shell 15.29%.

### Worst Screenshot Differences — Headless

| Rank | Host                     | Diff % | Severity | Type            |
|------|--------------------------|--------|----------|-----------------|
| 979  | tgju.org                 | 97.9%  | 31.6     | layout_diff     |
| 947  | european-union.europa.eu | 90.7%  | 32.3     | layout_diff     |
| 150  | www.ebay.com             | 89.7%  | 48.5     | layout_diff     |
| 598  | www.amazon.com.br        | 83.0%  | 228.5    | missing_content |
| 6    | aws.amazon.com           | 77.1%  | 44.5     | layout_diff     |
| 465  | shopee.co.id             | 75.8%  | 61.5     | redirect_diff   |
| 725  | poki.com                 | 73.8%  | 41.7     | layout_diff     |

### Worst Screenshot Differences — Headless-Shell

| Rank | Host               | Diff % | Severity | Type            |
|------|--------------------|--------|----------|-----------------|
| 489  | www.freepik.com    | 99.4%  | 263.0    | missing_content |
| 979  | tgju.org           | 97.9%  | 31.6     | layout_diff     |
| 215  | www.autodesk.com   | 97.1%  | 267.7    | missing_content |
| 820  | www.lg.com         | 95.9%  | 268.8    | missing_content |
| 919  | www.dw.com         | 85.9%  | 33.7     | layout_diff     |
| 148  | www.webex.com      | 83.3%  | 262.3    | missing_content |
| 898  | www.jiomart.com    | 82.9%  | 241.1    | redirect_diff   |
| 395  | www.salesforce.com | 82.8%  | 254.6    | missing_content |

The headless-shell top offenders are almost all `missing_content` — sites serving blank/skeleton pages to headless-shell.

---

## 7. Structural, Title & Redirect Diffs

### Structural Elements

|                            | Headless  | Headless-Shell |
|----------------------------|-----------|----------------|
| Sites with structural diff | 20 (2.1%) | 45 (4.7%)     |

Most commonly missing from headless modes (elements present in headful but not headless):

| Element | Count |
|---------|-------|
| section | 24    |
| footer  | 21    |
| form    | 21    |
| nav     | 19    |
| header  | 18    |
| main    | 18    |

### Title & Redirect Diffs

|                  | Headless  | Headless-Shell |
|------------------|-----------|----------------|
| Title differs    | 8 (0.8%)  | 52 (5.4%)      |
| Redirect differs | 8 (0.8%)  | 13 (1.3%)      |

Headless-shell has **6.5x more title differences**, concentrated among JS-heavy sites that simply don't render in headless-shell.

---

## 8. Headless vs Headless-Shell: Head-to-Head

All 965 URLs were tested in both modes. Comparing severity scores:

- Headless-shell has higher severity on **70.5%** of URLs
- Headless has higher severity on **20.7%**
- Equal on 8.8%
- Mean severity gap: headless-shell is **11.78 points higher**
- Spearman rank correlation: **0.724** (strong rank correlation)
- Pearson correlation: 0.345 (weak linear — driven by HS outliers)

### Diff Type Transition Matrix

| Headless \ Headless-Shell | identical | layout_diff | missing_content | dom_diff | redirect_diff | hl_errored | hf_errored | both_err |
|---------------------------|-----------|-------------|-----------------|----------|---------------|------------|------------|----------|
| **identical** (295)       | **220**   | 45          | 13              | 0        | 3             | 7          | 3          | 4        |
| **layout_diff** (604)     | 6         | **549**     | 30              | 3        | 0             | 16         | 0          | 0        |
| **missing_content** (22)  | 0         | 2           | **11**          | 0        | 6             | 1          | 0          | 2        |
| **dom_diff** (8)          | 4         | 1           | 0               | **2**    | 0             | 0          | 0          | 1        |
| **redirect_diff** (8)     | 1         | 3           | 0               | 2        | **2**         | 0          | 0          | 0        |
| **both_errored** (26)     | 0         | 3           | 0               | 0        | 2             | 0          | 2          | **19**   |
| **hl_errored** (1)        | 1         | 0           | 0               | 0        | 0             | 0          | 0          | 0        |
| **hf_errored** (1)        | 1         | 0           | 0               | 0        | 0             | 0          | 0          | 0        |

Key transitions:
- **45 sites**: identical in headless → layout_diff in headless-shell
- **13 sites**: identical in headless → missing_content in headless-shell
- **30 sites**: layout_diff in headless → missing_content in headless-shell (escalation)
- **16 sites**: layout_diff in headless → headless_errored in headless-shell
- Only **6 sites**: layout_diff in headless → identical in headless-shell (HS better)

---

## 9. Notable Site Categories

### JS Framework Sites That Break in Headless-Shell

These modern sites use heavy JavaScript (React, Next.js, etc.) that headless-shell cannot execute. They render perfectly in standard headless but serve blank/skeleton pages to headless-shell:

| Host               | HL Severity | HS Severity | HS Type         |
|--------------------|-------------|-------------|-----------------|
| www.lg.com         | 3.11        | 268.8       | missing_content |
| www.autodesk.com   | 3.14        | 267.7       | missing_content |
| unity.com          | 2.52        | 263.6       | missing_content |
| www.freepik.com    | 3.72        | 263.0       | missing_content |
| www.webex.com      | 2.51        | 262.3       | missing_content |
| www.salesforce.com | 3.42        | 262.2       | missing_content |
| www.mi.com         | 6.50        | 261.2       | missing_content |
| www.macys.com      | 2.36        | 260.2       | missing_content |
| www.servicenow.com | 2.85        | 257.0       | missing_content |
| wordpress.com      | 1.25        | 255.6       | missing_content |
| www.reddit.com     | 0.00        | 242.4       | missing_content |

### Anti-Bot Detection Targeting Standard Headless

These 13 sites render identically under headless-shell but show differences under standard headless, suggesting they specifically fingerprint headless Chrome (despite our anti-detection measures):

| Host                | HL Severity | HL Type         |
|---------------------|-------------|-----------------|
| www.ieee.org        | 143.3       | dom_diff        |
| www.yelp.com        | 96.8        | dom_diff        |
| www.dailymotion.com | 88.4        | missing_content |
| www.crazygames.com  | 72.3        | missing_content |
| portal.tds.net      | 70.3        | dom_diff        |
| www.binance.com     | 57.5        | dom_diff        |
| www.ebay.com        | 48.5        | layout_diff     |
| rutube.ru           | 30.6        | layout_diff     |
| www.icloud.com      | 16.6        | layout_diff     |
| www.figma.com       | 13.7        | layout_diff     |
| www.freewheel.com   | 12.0        | layout_diff     |
| myshopify.com       | 6.0         | layout_diff     |

### Amazon Domains Across Modes

| Host              | Rank | HL Sev | HS Sev | HL Type         | HS Type         |
|-------------------|------|--------|--------|-----------------|-----------------|
| aws.amazon.com    | 6    | 44.5   | 21.9   | layout_diff     | layout_diff     |
| www.amazon.com    | 17   | 7.5    | 99.3   | layout_diff     | missing_content |
| www.amazon.co.jp  | 83   | 7.7    | 2.3    | layout_diff     | layout_diff     |
| www.amazon.de     | 270  | 11.0   | 36.9   | layout_diff     | layout_diff     |
| www.amazon.co.uk  | 286  | 3.1    | 7.0    | layout_diff     | layout_diff     |
| www.amazon.fr     | 431  | 6.1    | 114.3  | layout_diff     | missing_content |
| www.amazon.ca     | 442  | 3.7    | 56.1   | layout_diff     | layout_diff     |
| www.amazon.in     | 477  | 4.3    | 54.7   | layout_diff     | missing_content |
| www.amazon.es     | 494  | 12.5   | 112.4  | layout_diff     | missing_content |
| www.amazon.it     | 508  | 37.6   | 118.0  | layout_diff     | missing_content |
| www.amazon.com.br | 598  | 228.5  | 225.1  | missing_content | missing_content |
| www.amazon.com.mx | 702  | 80.3   | 76.5   | dom_diff        | missing_content |
| www.amazon.eg     | 871  | 42.2   | 51.5   | layout_diff     | layout_diff     |

Amazon.com and most regional variants show significantly worse rendering in headless-shell (severity 50–118) compared to headless (severity 4–38). Amazon.com.br is an outlier — broken in both modes (severity ~225).

### Sites Where Headless-Shell Errors but Headless Works

24 sites errored in headless-shell but rendered successfully in headless:

| Host                   | Rank | HL Severity | HL Type         |
|------------------------|------|-------------|-----------------|
| www.adobe.com          | 48   | 0.25        | identical       |
| www.hpe.com            | 202  | 3.41        | layout_diff     |
| www.ea.com             | 205  | 2.33        | layout_diff     |
| www.washingtonpost.com | 222  | 5.13        | identical       |
| www.bloomberg.com      | 237  | 24.15       | layout_diff     |
| www.walmart.com        | 305  | 163.1       | missing_content |
| www.mcafee.com         | 308  | 7.55        | layout_diff     |
| www.fidelity.com       | 355  | 1.71        | identical       |
| www.mckinsey.com       | 561  | 0.04        | identical       |
| www.usnews.com         | 742  | 9.00        | layout_diff     |

---

## 10. Conclusions & Recommendations

### Key Findings

1. **Standard headless is far more compatible than headless-shell.** It renders 30.6% of sites identically (vs 24.1%) and has a mean severity of 9.83 (vs 21.61). Headless-shell has 5x more sites with severity > 100.

2. **Headless-shell fails fundamentally on modern JS-framework sites.** Sites built with React, Next.js, and similar frameworks (salesforce.com, autodesk.com, unity.com, wordpress.com, reddit.com) serve blank or skeleton pages to headless-shell — severity 240–268 vs < 10 in standard headless.

3. **Headless-shell provides substantial resource savings.** At ~52% of headful's RSS memory (582 MB vs 1,130 MB) and ~78% of CPU time, it's viable for sites that don't require JS rendering fidelity.

4. **Headful and headless are nearly identical** in resource usage (1.06x RSS, 1.01x CPU), DOM content (1.00x), and network behavior (1.00x). The rendering pipeline is essentially the same.

5. **85–88% of sites show some screenshot difference** in both modes, but the vast majority are minor (median diff ~4–6%). Only 2.3–5.0% show > 50% pixel difference.

6. **13 sites specifically detect standard headless but not headless-shell**, including ieee.org, yelp.com, dailymotion.com, ebay.com, and binance.com. These likely use fingerprinting techniques beyond `AutomationControlled` and UA spoofing — candidates for further investigation.

7. **Navigation timing is roughly equivalent** across all modes (within 5% for DOM-level metrics). Headless-shell shows higher DNS/connect/TTFB (likely sequential scheduling effect, not inherent overhead).

8. **77.2% of sites have some detectable rendering difference** in at least one headless mode. Perfect headful parity remains elusive even with anti-detection measures.

### Recommendations

- **Use standard headless for fidelity-critical tasks.** Its rendering is nearly identical to headful, with only ~6% more RSS overhead.
- **Use headless-shell only for simple, static sites** where memory/CPU savings justify the rendering tradeoffs.
- **Investigate the 13 headless-detected sites** for additional fingerprinting vectors (canvas, WebGL, font enumeration, timing attacks).
- **Amazon.com.br is an outlier** — broken in both modes, possibly geo-based blocking or aggressive bot detection.
- **The 75 sites that break only in headless-shell** (wordpress.com, reddit.com, salesforce.com, etc.) confirm that headless-shell's stripped rendering engine cannot handle modern web applications.
