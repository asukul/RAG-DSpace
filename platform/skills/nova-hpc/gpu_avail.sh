#!/usr/bin/env bash
# Nova GPU availability + hardware specs. Run from WSL (sinfo runs on Nova; awk runs locally).
#   tr -d '\r' < gpu_avail.sh | bash      (if this file has CRLF)
#   bash gpu_avail.sh                      (if LF)
# FREE/USED/TOT are LIVE from Slurm. VRAM/CUDA/MEMBW/FP16/ARCH are STATIC NVIDIA datasheet
# figures (Slurm doesn't track them). a100 VRAM confirmed 80GB from jobs (81920 MiB).
# rtx_6000 / rtx_pro_6000 / v100 specs are approximate — verify via nvidia-smi in a job.
ssh -n nova "sinfo -N -h -O 'NodeHost:20,Gres:50,GresUsed:50'" 2>/dev/null | awk '
BEGIN{
  no=split("a100 a100-pcie h200 gh200 rtx_pro_6000 l40s a40 rtx_6000 v100-sxm2-32G v100 rtx_2080_Ti",ORD," ")
  VR["a100"]=80;          CU["a100"]=6912;   BW["a100"]=2039; FP["a100"]=312; AR["a100"]="Ampere SXM4 HBM2e"
  VR["a100-pcie"]=40;     CU["a100-pcie"]=6912; BW["a100-pcie"]=1555; FP["a100-pcie"]=312; AR["a100-pcie"]="Ampere PCIe HBM2"
  VR["h200"]=141;         CU["h200"]=16896;  BW["h200"]=4800; FP["h200"]=990; AR["h200"]="Hopper HBM3e"
  VR["gh200"]=96;         CU["gh200"]=16896; BW["gh200"]=4000; FP["gh200"]=990; AR["gh200"]="Hopper+Grace ARM (H100)"
  VR["rtx_pro_6000"]=96;  CU["rtx_pro_6000"]=24064; BW["rtx_pro_6000"]=1792; FP["rtx_pro_6000"]="~"; AR["rtx_pro_6000"]="Blackwell GDDR7"
  VR["l40s"]=48;          CU["l40s"]=18176;  BW["l40s"]=864;  FP["l40s"]=362; AR["l40s"]="Ada GDDR6"
  VR["a40"]=48;           CU["a40"]=10752;   BW["a40"]=696;   FP["a40"]=150; AR["a40"]="Ampere GDDR6"
  VR["rtx_6000"]=24;      CU["rtx_6000"]=4608; BW["rtx_6000"]=672; FP["rtx_6000"]="~130"; AR["rtx_6000"]="Turing? verify"
  VR["v100-sxm2-32G"]=32; CU["v100-sxm2-32G"]=5120; BW["v100-sxm2-32G"]=900; FP["v100-sxm2-32G"]=125; AR["v100-sxm2-32G"]="Volta HBM2"
  VR["v100"]=16;          CU["v100"]=5120;   BW["v100"]=900;  FP["v100"]=125; AR["v100"]="Volta (16/32GB)"
  VR["rtx_2080_Ti"]=11;   CU["rtx_2080_Ti"]=4352; BW["rtx_2080_Ti"]=616; FP["rtx_2080_Ti"]=107; AR["rtx_2080_Ti"]="Turing GDDR6"
}
!s[$1]++{n=split($2,T,",");m=split($3,U,",")
  for(i=1;i<=n;i++)if(T[i]~/^gpu:/){split(T[i],a,":");sub(/\(.*/,"",a[3]);t[a[2]]+=a[3]}
  for(i=1;i<=m;i++)if(U[i]~/^gpu:/){split(U[i],a,":");sub(/\(.*/,"",a[3]);u[a[2]]+=a[3]}}
END{
  printf "%-15s %4s %4s %4s | %5s %6s %8s %7s  %s\n","GPU (gres)","FREE","USE","TOT","VRAM","CUDA","MEM-BW","FP16T","ARCH (datasheet)"
  printf "%-15s %4s %4s %4s | %5s %6s %8s %7s\n","","","","","GB","cores","GB/s","TFLOP",""
  for(i=1;i<=no;i++){k=ORD[i]; if(k in t) printf "%-15s %4d %4d %4d | %5s %6s %8s %7s  %s\n", k, t[k]-u[k], u[k], t[k], VR[k], CU[k], BW[k], FP[k], AR[k]}
  for(k in t) if(!(k in VR)) printf "%-15s %4d %4d %4d | %5s %6s %8s %7s  %s\n", k, t[k]-u[k], u[k], t[k], "?","?","?","?","(no spec on file)"
}'
