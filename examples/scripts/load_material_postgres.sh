#!/bin/bash
#SBATCH --job-name=load_material
#SBATCH -o <path>/logs/dsp2026-%J.txt
#SBATCH -p long
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=24:00:00
#SBATCH --mail-type=END
#SBATCH --mail-user=<email>
#SBATCH --nodelist=<node>

echo "Running in node: $(hostname)"
echo "Running in: $(pwd)"

module load Python cuDNN
source ../venv/bin/activate

DATA=<path>/ProjectNew
INPUT=<path>/ProjectNew/input

DB_HOST=127.0.0.1
DB_PORT=5432
DB_USER=<username>
DB_NAME=postgres

echo "Using DB: $DB_HOST:$DB_PORT"

echo "Waiting for Postgres..."

for i in {1..30}; do
  singularity exec \
    postgres.sif \
    psql -h 127.0.0.1 -U $DB_USER -d postgres -c '\q' \
    && echo "Postgres is up" && break
  sleep 2
done

echo "CLIENT HOST=$(hostname)"

echo "Running orchestrator..."

CITIES=(
"10Nanjing"
"11Qingdao"
"12Kunming"
"13Xi'an"
"14Haerbin"
"15Shenyang"
"16Changsha"
"17Jinan"
"18Zhengzhou"
"19Xiamen"
"20Fuzhou"
"21Changchun"
"22Nanning"
"23Urumqi"
"24Ningbo"
"25Guiyang"
"26Hefei"
"27Shijiazhuang"
"28Taiyuan"
"29Nanchang"
"30Haikou"
"31Xining"
"32Yinchuan"
"33Hohhot"
"34Nanzhou"
"35Lhasa"
"36Chengdu"
"3Tianjin"
"4Chongqing"
"7Wuhan"
"8Hangzhou"
"9Dalian"
"1Beijing"
"2Shanghai"
"5Guangzhou"
"6Shenzhen"
)

echo "Starting processing ${#CITIES[@]} cities..."

for CITY in "${CITIES[@]}"; do
echo "======================="
echo "Processing CITY: $CITY"
echo "======================="

singularity exec \
--bind $DATA:/data \
--bind $INPUT:/input \
orchestrator.sif \
python -m pipeline.orchestrator \
--db-dsn postgresql://<username>@127.0.0.1:5432/postgres \
upload \
--csv-folder /input/$CITY \
--image-folder /input/$CITY

done

echo "Upload finished"

