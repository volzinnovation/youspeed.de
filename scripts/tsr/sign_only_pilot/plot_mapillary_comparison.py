#!/usr/bin/env python3
"""Presentation-only redraw from frozen numeric results; no inference or selection."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
p=Path('/job/balanced-v1/mapillary-benchmark');summary=json.loads((p/'summary.json').read_text());results=summary['results'];names=list(results)
fig,axes=plt.subplots(1,2,figsize=(13,7),constrained_layout=True)
for i,name in enumerate(names):
 a=results[name]['development_calibrated']['classified_primary'];b=results[name]['fixed']['classified_primary']
 axes[0].barh(i-.18,a['reference_coverage'] or 0,height=.34,color='#187c91',label='Dev-calibrated' if i==0 else None)
 axes[0].barh(i+.18,b['reference_coverage'] or 0,height=.34,color='#9bbac0',label='Fixed phone threshold' if i==0 else None)
 axes[1].barh(i,a['unmatched_per_image'],height=.6,color='#ad723b')
for ax in axes:ax.set_yticks(range(len(names)),names);ax.invert_yaxis();ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
axes[0].set_xlim(0,1);axes[0].set_xlabel('Fraction of available classified references matched')
axes[1].set_xlabel('Unmatched predictions per image (not verified false positives)')
handles,labels=axes[0].get_legend_handles_labels();axes[1].legend(handles,labels,loc='lower right',title='Left panel')
fig.suptitle('Mapillary automatic-reference agreement · incomplete labels');fig.savefig(p/'comparison.png',dpi=150);plt.close(fig)
