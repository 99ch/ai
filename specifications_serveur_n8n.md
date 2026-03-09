# Besoin DG – Ressources serveur à valider

## 1. Objet
Ce document liste uniquement les éléments à fournir/valider côté direction pour finaliser la mise en production.

## 2. Serveur à provisionner (pré-production)
- **CPU** : 4 vCPU
- **RAM** : 8 Go
- **Stockage** : 120 Go SSD NVMe (extensible)
- **Réseau** : 1 IP publique fixe
- **OS** : Ubuntu Server 22.04 LTS

> Évolution possible en production : 8 vCPU / 16 Go RAM / 300 Go SSD NVMe.

## 3. Éléments à fournir par la direction
- Mise à disposition du serveur avec les caractéristiques ci-dessus
- Attribution de l’IP publique fixe
- Validation du nom de domaine / sous-domaine à utiliser 
- Transmission des accès administrateur serveur (SSH)

## 4. Validation sécurité réseau
- Autoriser l’exposition web sur ports **80/443**
- Restreindre l’accès **SSH** à mon IP (ou via VPN)

## 5. Statut projet
- KPI IA intégrés
- Frontend amélioré
- Reste à finaliser : Disponibilité du serveur pour déploiement n8n
