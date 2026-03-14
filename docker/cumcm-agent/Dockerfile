# =============================================================================
#  CUMCM-Agent 计算环境
#  Python 3.11 + TeX Live Full + 科学计算全家桶（全开源，无需 License）
# =============================================================================

FROM python:3.11-slim-bookworm

LABEL maintainer="CUMCM-Master" \
      description="Full scientific computing + LaTeX environment for CUMCM & MCM/ICM"

# ── 系统依赖 ──────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 构建工具
    build-essential gcc gfortran git curl wget \
    # TeX Live（含 CJK / XeLaTeX / PdfLaTeX）
    texlive-full \
    # 字体（中文支持）
    fonts-noto-cjk fonts-noto-cjk-extra \
    # 科学计算系统依赖
    libopenblas-dev liblapack-dev libhdf5-dev \
    libgomp1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    # PDF 工具
    ghostscript poppler-utils \
    # 其他工具
    ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 更新 tlmgr 并安装额外宏包
# mcmthesis: 美赛论文模板 (https://github.com/latexstudio-org/mcmthesis)
# algorithm2e: 算法伪代码环境
# siunitx: 单位格式化
# cleveref: 智能交叉引用
RUN tlmgr update --self 2>/dev/null || true && \
    tlmgr install mcmthesis algorithm2e siunitx cleveref \
                  microtype enumitem caption 2>/dev/null || true

# 若 tlmgr 安装 mcmthesis 失败（网络问题），从 GitHub 直接安装
RUN if ! kpsewhich mcmthesis.cls > /dev/null 2>&1; then \
        mkdir -p /tmp/mcmthesis && \
        curl -fsSL https://github.com/latexstudio-org/mcmthesis/archive/refs/heads/master.tar.gz \
             -o /tmp/mcmthesis.tar.gz && \
        tar -xzf /tmp/mcmthesis.tar.gz -C /tmp/mcmthesis --strip-components=1 && \
        cp /tmp/mcmthesis/mcmthesis.cls \
           $(kpsewhich -var-value TEXMFLOCAL)/tex/latex/mcmthesis/ 2>/dev/null || \
        cp /tmp/mcmthesis/mcmthesis.cls /usr/share/texlive/texmf-dist/tex/latex/misc/ && \
        mktexlsr 2>/dev/null || true && \
        rm -rf /tmp/mcmthesis /tmp/mcmthesis.tar.gz; \
    fi

# ── Python 科学计算库 ─────────────────────────────────────────────────────
# 分层安装以利用 Docker 缓存
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 基础科学计算
RUN pip install --no-cache-dir \
    numpy==1.26.4 \
    scipy==1.13.1 \
    pandas==2.2.2 \
    sympy==1.12 \
    statsmodels==0.14.2

# 机器学习
RUN pip install --no-cache-dir \
    scikit-learn==1.5.1 \
    xgboost==2.1.0 \
    lightgbm==4.4.0

# 深度学习（PyTorch CPU，避免镜像过大；如需 GPU 版修改 index-url）
RUN pip install --no-cache-dir \
    torch==2.3.1 torchvision==0.18.1 \
    --index-url https://download.pytorch.org/whl/cpu

# 优化求解器（开源）
RUN pip install --no-cache-dir \
    cvxpy==1.5.3 \
    cvxopt==1.3.2 \
    pyomo==6.7.3 \
    or-tools==9.10.4067 \
    pulp==2.8.0 \
    gekko==1.2.1

# 数据处理与可视化
RUN pip install --no-cache-dir \
    matplotlib==3.9.1 \
    seaborn==0.13.2 \
    plotly==5.22.0 \
    pillow==10.4.0 \
    openpyxl==3.1.5 \
    xlrd==2.0.1 \
    networkx==3.3

# PDF/文档处理
RUN pip install --no-cache-dir \
    pdfplumber==0.11.4 \
    pypdf==4.3.1 \
    python-docx==1.1.2

# 工具库
RUN pip install --no-cache-dir \
    tqdm==4.66.4 \
    rich==13.7.1 \
    click==8.1.7 \
    watchdog==4.0.1

# ── 工作目录 ──────────────────────────────────────────────────────────────
WORKDIR /workspace

# matplotlib 中文字体配置
RUN mkdir -p ~/.config/matplotlib && \
    echo "font.family: Noto Sans CJK SC" > ~/.config/matplotlib/matplotlibrc || true

CMD ["/bin/bash"]
