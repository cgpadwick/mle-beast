Customer Churn Prediction Dataset
=================================

Synthetic customer information for predicting churn.

Features:
- tenure: Number of months the customer has been with the company (1-72)
- monthly_charges: Monthly bill amount in dollars (20-100)
- total_charges: Total amount billed (approximately monthly_charges * tenure with noise)
- contract_type: 0=month-to-month, 1=one-year, 2=two-year
- has_support: 0=no tech support, 1=has tech support

Target:
- churned: 0=stayed, 1=left the company

Files:
- train.csv: 400 samples for training
- test.csv:  100 samples for evaluation
Same schema in both splits.
