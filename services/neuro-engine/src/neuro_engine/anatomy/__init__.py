"""Structural anatomy: MRI volume metadata, FreeSurfer surfaces and parcellations,
coordinate transforms and render-ready asset preparation (ADR-0010).

Offline batch code. The acquisition path never imports this package; the HTTP
layer only reads assets that were prepared beforehand.
"""
