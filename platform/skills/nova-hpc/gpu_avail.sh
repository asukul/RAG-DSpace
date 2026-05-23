#!/usr/bin/env bash
# Nova GPU availability + hardware specs — colorized & sortable.
# Usage:  gpu_avail.sh [SORT_COL] [asc|desc]
#   SORT_COL: type free used tot vram cuda bw fp16     (default: free desc)
#   e.g.  gpus            gpus vram        gpus cuda asc      gpus free
# Colors auto-enable on a terminal, plain text when piped/redirected.
# FREE/USED/TOT are LIVE from Slurm (sinfo on Nova). VRAM/CUDA/MEMBW/FP16/ARCH are STATIC
# NVIDIA datasheet figures (Slurm doesn't track them). a100 VRAM confirmed 80GB from jobs;
# rtx_6000 / rtx_pro_6000 / v100 are approximate — verify with nvidia-smi in a job.
set -uo pipefail
SCOL="${1:-free}"; SDIR="${2:-}"
case "$SCOL" in
  type) F=1; DEF=asc ;; free) F=2; DEF=desc ;; used) F=3; DEF=desc ;; tot) F=4; DEF=desc ;;
  vram) F=5; DEF=desc ;; cuda) F=6; DEF=desc ;; bw) F=7; DEF=desc ;; fp16) F=8; DEF=desc ;;
  *) echo "unknown column '$SCOL' — use: type free used tot vram cuda bw fp16" >&2; exit 2 ;;
esac
[ -z "$SDIR" ] && SDIR="$DEF"
SARGS=(-t$'\t' -k"$F")
[ "$F" -ne 1 ] && SARGS+=(-n)
[ "$SDIR" = desc ] && SARGS+=(-r)
if [ -t 1 ]; then B=$'\e[1m'; DIM=$'\e[2m'; G=$'\e[1;32m'; R=$'\e[31m'; CY=$'\e[36m'; N=$'\e[0m'
else B=; DIM=; G=; R=; CY=; N=; fi

ssh -n nova "sinfo -N -h -O 'NodeHost:20,Gres:50,GresUsed:50'" 2>/dev/null | awk '
BEGIN{ OFS="\t"
  no=split("a100 a100-pcie h200 gh200 rtx_pro_6000 l40s a40 rtx_6000 v100-sxm2-32G v100 rtx_2080_Ti",ORD," ")
  VR["a100"]=80;CU["a100"]=6912;BW["a100"]=2039;FP["a100"]=312;AR["a100"]="Ampere SXM4 HBM2e"
  VR["a100-pcie"]=40;CU["a100-pcie"]=6912;BW["a100-pcie"]=1555;FP["a100-pcie"]=312;AR["a100-pcie"]="Ampere PCIe HBM2"
  VR["h200"]=141;CU["h200"]=16896;BW["h200"]=4800;FP["h200"]=990;AR["h200"]="Hopper HBM3e"
  VR["gh200"]=96;CU["gh200"]=16896;BW["gh200"]=4000;FP["gh200"]=990;AR["gh200"]="Hopper+Grace ARM"
  VR["rtx_pro_6000"]=96;CU["rtx_pro_6000"]=24064;BW["rtx_pro_6000"]=1792;FP["rtx_pro_6000"]=0;AR["rtx_pro_6000"]="Blackwell GDDR7"
  VR["l40s"]=48;CU["l40s"]=18176;BW["l40s"]=864;FP["l40s"]=362;AR["l40s"]="Ada GDDR6"
  VR["a40"]=48;CU["a40"]=10752;BW["a40"]=696;FP["a40"]=150;AR["a40"]="Ampere GDDR6"
  VR["rtx_6000"]=24;CU["rtx_6000"]=4608;BW["rtx_6000"]=672;FP["rtx_6000"]=130;AR["rtx_6000"]="Turing? verify"
  VR["v100-sxm2-32G"]=32;CU["v100-sxm2-32G"]=5120;BW["v100-sxm2-32G"]=900;FP["v100-sxm2-32G"]=125;AR["v100-sxm2-32G"]="Volta HBM2"
  VR["v100"]=16;CU["v100"]=5120;BW["v100"]=900;FP["v100"]=125;AR["v100"]="Volta 16/32GB"
  VR["rtx_2080_Ti"]=11;CU["rtx_2080_Ti"]=4352;BW["rtx_2080_Ti"]=616;FP["rtx_2080_Ti"]=107;AR["rtx_2080_Ti"]="Turing GDDR6"
}
!s[$1]++{n=split($2,T,",");m=split($3,U,",")
  for(i=1;i<=n;i++)if(T[i]~/^gpu:/){split(T[i],a,":");sub(/\(.*/,"",a[3]);t[a[2]]+=a[3]}
  for(i=1;i<=m;i++)if(U[i]~/^gpu:/){split(U[i],a,":");sub(/\(.*/,"",a[3]);u[a[2]]+=a[3]}}
END{
  for(i=1;i<=no;i++){k=ORD[i]; if(k in t) print k,t[k]-u[k],u[k],t[k],VR[k],CU[k],BW[k],FP[k],AR[k]}
  for(k in t) if(!(k in VR)) print k,t[k]-u[k],u[k],t[k],0,0,0,0,"(no spec on file)"
}' | sort "${SARGS[@]}" | awk -F'\t' -v B="$B" -v DIM="$DIM" -v G="$G" -v R="$R" -v CY="$CY" -v N="$N" -v sc="$SCOL" -v sd="$SDIR" '
BEGIN{
  printf "%sNova GPU availability%s  %s(VRAM GB · MEM-BW GB/s · FP16 TFLOPS, datasheet)  sorted by %s %s%s\n", B,N,DIM,sc,sd,N
  printf "%s%-15s %4s %4s %4s | %4s %6s %6s %5s  %s%s\n", B,"GPU (gres)","FREE","USE","TOT","VRAM","CUDA","MEMBW","FP16","ARCH",N
}
{ fc=($2+0>0)?G:R; fp=($8+0>0)?$8:"~"
  printf "%s%-15s%s %s%4s%s %4s %4s | %4s %6s %6s %5s  %s%s%s\n", CY,$1,N, fc,$2,N, $3,$4, $5,$6,$7,fp, DIM,$9,N }'
