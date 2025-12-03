# Overview

This FastAPI service is designed for a network of hair-transplant clinics that operate multiple landing pages. The clinics run advertising campaigns through Yandex Direct and direct traffic to these pages. During operation, they discovered a persistent discrepancy: Yandex counters reported high conversion rates, while the number of actual submissions recorded in the CRM was significantly lower.

This application was created to address that gap.

## Purpose

### 1. Validate actual user submissions  
Ad platform click metrics frequently overestimate conversions by counting button presses as completed actions. This service tracks whether a visitor genuinely initiated contact through a social network or simply clicked a button without following through.

### 2. Collect marketing and behavioral data  
The service captures UTM parameters, time spent on the site, and other request metadata. These records are written to a Google Sheet for subsequent analysis and lead-quality assessment.

## DISCLAIMER

The solution is tailored for the clinic network’s specific landing pages and CRM workflows. It is not a plug-and-play module; proper integration requires configuration on each site and within the associated CRM system.

---

Below is a visual illustration of the entire process and data flow.

<img width="4472" height="4227" alt="image" src="https://github.com/user-attachments/assets/ba3edbd8-e8ef-428c-8e0b-26a3ce1458c5" />
