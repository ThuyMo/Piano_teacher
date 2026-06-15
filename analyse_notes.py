import pandas as pd 
from model.helper import mid_to_pd, pd_to_str, str_to_mid
import sys
import matplotlib.pyplot as plt

pd_df = mid_to_pd("artifact/test_RH.mid")

# main_note_duration = pd_df['duration'].median()/2
# processed_df = pd_df[pd_df['duration'] >= main_note_duration]
# pd_df["duration"].plot.box()
# plt.show()
processed_df = pd_df.copy()
processed_df = processed_df.groupby('grouped_time').apply(lambda x: x.loc[x['pitch'].idxmax()]).reset_index()

# Processed df 
str_processed = pd_to_str(processed_df)
str_to_mid(str_processed, "artifact/test_RH_processed.mid")
