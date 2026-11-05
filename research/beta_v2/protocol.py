"""Fixed prospective windows and conservative research decision rules."""
from datetime import datetime,timezone
from project_craps.common import instant
VERSION='beta-v2-nfl-ncaab-20261105'
HORIZONS={'DAY_AHEAD':(18*3600,30*3600),'EARLY':(2*3600,18*3600),'FINAL':(10*60,75*60)}
PROTOCOL=dict(version=VERSION,status='RESEARCH_ONLY',horizons=HORIZONS,primary_horizon='FINAL',primary_arm='rolling_calibrated',primary_score='game-balanced conditional winner Brier versus exact frozen official comparator; NCAAB logistic, NFL score-kernel conditional-on-no-tie',secondary='W/P/L Brier, uncapped logloss/support failures, margins/totals, actual offered lines and market-no-vig when authenticated; all exploratory',family_alpha=.05,primary_sports=2,primary_family_adjustment='Bonferroni across NFL and NCAAB; no selection among daily looks',practical_brier_improvement=.005,pilot={'NFL':30,'NCAAB':100},pilot_policy='First registered FINAL settled pilot games estimate variance/dependence only and are excluded from later confirmation; future confirmation sample/horizon must be frozen after pilot power planning. No daily efficacy claims.',minimum_week_blocks_readiness=8,confirmation_status='NOT_POWERED_UNTIL_PILOT_AND_CLUSTER_DESIGN_COMPLETE',promotion='Never automatic; independent source, eligibility, price, proper-score and untouched confirmation gates remain mandatory',research_refit_policy='Once daily; fixed algorithm/settings; fresh immutable bundle; no official model refits',optional_features='Only pregame source-bound measurements with separately validated coefficients; unknown stays unavailable',hypothetical_policy={'permitted_book':'Hard Rock Florida','one_ticket_per_event_across_horizons':True,'flat_unit_fraction':.01,'portfolio_daily_exposure_fraction':.05,'minimum_ev':.03,'real_approved_risk':0},source_authentication='Candidate capture is not independent authentication')

def horizon(kickoff,asof):
 lead=(instant(kickoff)-instant(asof)).total_seconds()
 for name,(lo,hi) in HORIZONS.items():
  if lo<=lead<hi:return name
 return None

def score_safety(scores,outcome):
 from .calibration import proper_scores
 return proper_scores(scores,outcome)

def readiness(pairs,weeks,sport,source_pass=False):
 floor=PROTOCOL['pilot'][sport]
 if pairs<floor:return dict(status='PILOT_KEEP_TESTING',remaining_pilot=floor-pairs,approved=False)
 if weeks<PROTOCOL['minimum_week_blocks_readiness']:return dict(status='INSUFFICIENT_TIME_BLOCKS',approved=False)
 return dict(status='POWER_DESIGN_AND_UNTOUCHED_CONFIRMATION_REQUIRED',source_pass=source_pass,approved=False)
