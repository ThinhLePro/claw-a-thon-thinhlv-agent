---
name: ai-cluster-network
description: "AI Cluster Network architecture and infrastructure design. Covers GPU node networking (NVLink, ConnectX, BlueField), five network planes (NVLink, Compute Fabric, Storage, Inband, OOB), NVIDIA DGX/HGX platforms, InfiniBand vs Ethernet comparison, RDMA/RoCE, Scalable Units (SU), rail-optimized topology, fat-tree design, UFM management, and BlueField DPU deployment. Trigger: AI network, GPU cluster, NVLink, ConnectX, BlueField, DPU, InfiniBand, RDMA, RoCE, Compute Fabric, SuperPOD, Scalable Unit, HGX, DGX, Spectrum-X, rail-optimized, lossless network, AI infrastructure."
---

# AI Cluster Network

Kiến trúc hạ tầng mạng cho cụm GPU (AI Network), bao gồm thiết kế các Network Planes, NIC types, và topology.

## Interaction Guidelines

- Khi tư vấn về AI network, luôn xác định rõ **Network Plane** nào đang được hỏi (NVLink, Compute, Storage, Inband, OOB)
- Phân biệt rõ **InfiniBand vs Ethernet** — mỗi loại có use case và transceivers riêng
- Giải thích khái niệm **Scalable Unit (SU)** khi nói về scaling
- Nhấn mạnh yêu cầu **lossless network** cho Compute Fabric
- Reference số liệu cụ thể về NIC models, tốc độ, và cấu hình

## Topics Covered

| Topic | Nội dung |
|---|---|
| GPU Node Architecture | HGX vs DGX, NIC types (ConnectX, BlueField SuperNIC, BlueField DPU) |
| NVLink Network | Intra-node GPU interconnect, NVSwitch, bandwidth per generation |
| Compute Fabric | East/West GPU↔GPU, rail-optimized topology, SU sizing, InfiniBand/Ethernet |
| Storage Network | RDMA, GPUDirect Storage, BlueField DPU, oversubscription |
| Inband Network | Management, job scheduling (Slurm/K8s), Internet access |
| OOB Network | BMC, BF-BMC, PXE boot, iDRAC |
| InfiniBand Generations | NDR (400G), XDR (800G), lane speeds, PAM4 |
| NIC Models | ConnectX-8/9, BlueField-3/4, naming conventions |
| Switches | Quantum (IB), Spectrum-X (Ethernet), UFM management |
| HA Design | BlueField NIC redundancy, bonding vs RDMA ECMP |

---

Read `references/ai-cluster-network.md` for the complete technical reference.
