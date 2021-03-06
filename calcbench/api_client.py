'''
Created on Mar 14, 2015

@author: Andrew Kittredge
@copyright: Calcbench, Inc.
@contact: andrew@calcbench.com
'''
from __future__ import print_function
import os
import requests
import json
import warnings

try:
    import pandas as pd  
    import numpy as np
except ImportError:
    "Can't find pandas, won't be able to use the functions that return DataFrames."
    pass


_SESSION_STUFF = {'calcbench_user_name' : os.environ.get("CALCBENCH_USERNAME"),
                 'calcbench_password' : os.environ.get("CALCBENCH_PASSWORD"),
                 'api_url_base' : "https://www.calcbench.com/api/{0}",
                 'logon_url' : 'https://www.calcbench.com/account/LogOnAjax',
                 'domain' : 'https://www.calcbench.com/{0}',
                 'ssl_verify' : True,
                 'session' : None,
                 'timeout' : 60 * 20,  # twenty minute content request timeout, by default
                 }


def _calcbench_session():  
    session = _SESSION_STUFF.get('session')
    if not session:
        user_name = _SESSION_STUFF.get('calcbench_user_name')
        password = _SESSION_STUFF.get('calcbench_password')
        if not (user_name and password):
            raise ValueError("No credentials supplied, either call set_credentials or set \
                                CALCBENCH_USERNAME and CALCBENCH_PASSWORD environment variables.")
        session = requests.Session()
        if _SESSION_STUFF.get('proxies'):
            session.proxies.update(_SESSION_STUFF['proxies'])
        r = session.post(_SESSION_STUFF['logon_url'],
                  {'email' : user_name, 
                   'strng' : password, 
                   'rememberMe' : 'true'},
                  verify=_SESSION_STUFF['ssl_verify'],
                  timeout=_SESSION_STUFF['timeout'])
        r.raise_for_status()
        if r.text != 'true':
            raise ValueError('Incorrect Credentials, use the email and password you use to login to Calcbench.')
        else:
            _SESSION_STUFF['session'] = session
    return session

def _rig_for_testing(domain='localhost:444', suppress_http_warnings=True):
    _SESSION_STUFF['api_url_base'] = 'https://' + domain + '/api/{0}'
    _SESSION_STUFF['logon_url'] = 'https://' + domain + '/account/LogOnAjax'
    _SESSION_STUFF['domain'] = 'https://' + domain + '/{0}'
    _SESSION_STUFF['ssl_verify'] = False
    _SESSION_STUFF['session'] = None
    if suppress_http_warnings:
        from requests.packages.urllib3.exceptions import InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

def _json_POST(end_point, payload):
    url = _SESSION_STUFF['api_url_base'].format(end_point)
    response = _calcbench_session().post(url,
                                        data=json.dumps(payload),
                                        headers={'content-type' : 'application/json'},
                                        verify=_SESSION_STUFF['ssl_verify'],
                                        timeout=_SESSION_STUFF['timeout'])
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(response.content)
        raise e
    return response.json()

def set_credentials(cb_username, cb_password):
    '''Set your calcbench credentials.
    
    username is the email address you use to login to calcbench.com.
    '''
    _SESSION_STUFF['calcbench_user_name'] = cb_username
    _SESSION_STUFF['calcbench_password'] = cb_password
    _calcbench_session() #Make sure credentials work.
    
def set_proxies(proxies):
    _SESSION_STUFF['proxies'] = proxies

def normalized_dataframe(company_identifiers=[], 
                    metrics=[], 
                    start_year=None, 
                    start_period=None,
                    end_year=None,
                    end_period=None,
                    entire_universe=False,
                    filing_accession_number=None,
                    point_in_time=False,
                    year=None,
                    period=None,
                    all_history=False,
                    period_type=None
                    ):
    '''Normalized data.
    
    Get normalized data from Calcbench.  Each point is normalized by economic concept and time period.
    
    Args:
        company_identifiers: a sequence of tickers (or CIK codes), eg ['msft', 'goog', 'appl']
        metrics: a sequence of metrics, see the full list @ https://www.calcbench.com/home/excel#availableMetrics eg. ['revenue', 'accountsreceivable']
        start_year: first year of data
        start_period: first quarter to get, for annual data pass 0, for quarters pass 1, 2, 3, 4
        end_year: last year of data
        end_period: last_quarter to get, for annual data pass 0, for quarters pass 1, 2, 3, 4        
        entire_universe: Get data for all companies, this can take a while, talk to Calcbench before you do this in production.
        accession_id: Filing Accession ID from the SEC's Edgar system.
        year: Get data for a single year, defaults to annual data.
        period_type: Either "annual" or "quarterly".
    Returns:
        A Pandas.Dataframe with the periods as the index and columns indexed by metric and ticker
    '''
    if all_history and not period_type:
        raise ValueError('For all history you must specify a period_type')
    data = normalized_raw(company_identifiers=list(company_identifiers), 
                          metrics=metrics, 
                          start_year=start_year,
                          start_period=start_period, 
                          end_year=end_year, 
                          end_period=end_period, 
                          entire_universe=entire_universe,
                          point_in_time=point_in_time,
                          filing_accession_number=filing_accession_number,
                          year=year,
                          period=period,
                          all_history=all_history,
                          period_type=period_type
                          )
    if not data:
        warnings.warn("No data found")
        return pd.DataFrame()
    
    quarterly = (start_period and end_period) or period_type == 'quarterly'
    if quarterly:
        build_period = _build_quarter_period
    else:
        build_period = _build_annual_period
   
    metrics_found = set()
    for d in data:                          
        d['period'] = build_period(d)
        d['ticker'] = d['ticker'].upper()
        try: # This is probably not necessary, we're doing it in the dataframe. akittredge January 2017.
            d['value'] = float(d['value'])
        except ValueError:
            pass
        metrics_found.add(d['metric'])
    
    missing_metrics = set(metrics) - metrics_found
    if missing_metrics:
        warnings.warn("Did not find metrics {0}".format(missing_metrics))
    data = pd.DataFrame(data)
    data.set_index(keys=['ticker', 'metric', 'period'],
                   inplace=True)
    
    try:
        data = data.unstack('metric')['value']
    except ValueError as e:
        if str(e) == 'Index contains duplicate entries, cannot reshape':
            print('Duplicate values', data[data.index.duplicated()])
        raise
    
    for column_name in data.columns.values:
        #Try to make the columns the right type
        try:
            data[column_name] = pd.to_numeric(data[column_name], errors='raise')
        except ValueError:
            if 'date' in column_name.lower():
                data[column_name] = pd.to_datetime(data[column_name], errors='coerce')
        
    for missing_metric in missing_metrics:
        data[missing_metric] = np.nan # We want columns for every requested metric.     
    data = data.unstack('ticker')
    return data
    
def _build_quarter_period(data_point):
    try:
        return pd.Period(year=data_point.pop('calendar_year'),
                 quarter=data_point.pop('calendar_period'),
                 freq='q')
    except ValueError:
        # DEI points (entity_name) etc, don't have periods.
        return pd.Period()      



def _build_annual_period(data_point):
    data_point.pop('calendar_period')
    return pd.Period(year=data_point.pop('calendar_year'), freq='a')

normalized_data = normalized_dataframe # used to call it normalized_data.
standardized_data = normalized_dataframe # Now it's called standardized data

def normalized_raw(company_identifiers=[],
                    metrics=[],
                    start_year=None,
                    start_period=None,
                    end_year=None,
                    end_period=None,
                    entire_universe=False,
                    filing_accession_number=None,
                    point_in_time=False,
                    include_trace=False,
                    update_date=None,
                    all_history=False,
                    year=None,
                    period=None,
                    period_type=None,
                    ):
    '''
    Normalized data.
    
    Get normalized data from Calcbench.  Each point is normalized by economic concept and time period.
    
    Args:
        company_identifiers: a sequence of tickers (or CIK codes), eg ['msft', 'goog', 'appl']
        metrics: a sequence of metrics, see the full list @ https://www.calcbench.com/home/excel#availableMetrics eg. ['revenue', 'accountsreceivable']
        start_year: first year of data
        start_period: first quarter to get, for annual data pass 0, for quarters pass 1, 2, 3, 4
        end_year: last year of data
        end_period: last_quarter to get, for annual data pass 0, for quarters pass 1, 2, 3, 4
        entire_universe: Get data for all companies, this can take a while, talk to Calcbench before you do this in production.
        accession_id: Filing Accession ID from the SEC's Edgar system.
        include_trace: Include the facts used to calculate the normalized value.
        year: Get data for a single year, defaults to annual data.
        period_type: Either "annual" or "quarterly"
        
    Returns:
        A list of dictionaries with keys ['ticker', 'calendar_year', 'calendar_period', 'metric', 'value'].
        
        For example
            [
                {
                    "ticker": "MSFT",
                    "calendar_year": 2010,
                    "calendar_period": 1,
                    "metric": "revenue",
                    "value": 14503000000
                },
                {
                    "ticker": "MSFT",
                    "calendar_year": 2010,
                    "calendar_period": 2,
                    "metric": "revenue",
                    "value": 16039000000
                },
            ]
    '''
    if [bool(company_identifiers), bool(entire_universe), bool(filing_accession_number)].count(True) != 1:
        raise ValueError("Must pass either company_identifiers and accession id or entire_universe=True")
    
    if filing_accession_number and any([company_identifiers, start_year, start_period, end_year, end_period, entire_universe, year, period]):
        raise ValueError("Accession IDs are specific to a filing, no other qualifiers make sense.")
    if year:
        if start_year or end_year:
            raise ValueError("Use year for a single period.  start_year and end_year for ranges.")
        start_year = end_year = year
    if period:
        if start_period or end_period:
            raise ValueError("Use period for a single period.  start_period and end_period are for ranges.")
        if period not in ('Y', 0) and (start_year or end_year):
            raise ValueError('With start_year or end_year only annual period works')
            
        start_period = end_period = period
    if period_type and period_type not in ('annual', 'quarterly'):
        raise ValueError('period_type must be either "annual" or "quarterly"')
        
    try:
        start_year = int(start_year)
    except (ValueError, TypeError):
        pass
    try:
        start_period = int(start_period)
    except (ValueError, TypeError):
        pass
    try:
        end_year = int(end_year)
    except (ValueError, TypeError):
        pass
    try:
        end_period = int(end_period)
    except (ValueError, TypeError):
        pass
    payload = {'pageParameters' : {'metrics' : metrics, 'includeTrace' : include_trace, 'pointInTime' : point_in_time,
                                   },
               'periodParameters' : {'year' : start_year, 
                                     'period' : start_period, 
                                     'endYear' : end_year,
                                     'endPeriod' : end_period, 
                                     'allHistory' : all_history, 
                                     'updateDate' : update_date and update_date.isoformat(),
                                     'periodType' : period_type,
                                     },
               'companiesParameters' : {'entireUniverse' : entire_universe, 
                                        'companyIdentifiers' : list(company_identifiers),
                                        }
               }

    return _json_POST("mappedData", payload)


def point_in_time(company_identifiers=[], 
                  all_footnotes=False, 
                  update_date=None, 
                  metrics=[], 
                  all_history=False,
                  entire_universe=False):
    '''
    Just for point-in-time footnotes now.
    '''


    data = mapped_raw(company_identifiers=company_identifiers, 
                      all_footnotes=all_footnotes, 
                      point_in_time=True,
                      update_date=update_date,
                      metrics=metrics,
                      all_history=all_history,
                      entire_universe=entire_universe)
    if not data:
        return pd.DataFrame()
    data = pd.DataFrame(data)
    period_number = pd.api.types.CategoricalDtype(categories=[1, 2, 3, 4, 5, 6, 0], ordered=True) # So annual is last in sorting.  5 and 6 are first half and 3QCUM.
    sort_columns = ['ticker', 'metric']
    if 'calendar_period' in data.columns:
        data.calendar_period = data.calendar_period.astype(period_number)
        sort_columns.extend(['calendar_year', 'calendar_period'])
    if 'fiscal_period' in data.columns:        
        data.fiscal_period = data.fiscal_period.astype(period_number) 
    return data.sort_values(sort_columns).reset_index(drop=True)

def mapped_raw(company_identifiers=[], all_footnotes=False, point_in_time=False, 
               update_date=None, metrics=[], all_history=False, entire_universe=False):
    payload = {
               'companiesParameters' : {'companyIdentifiers' : company_identifiers, 'entireUniverse' :  entire_universe},
               'pageParameters' : {'pointInTime' : point_in_time,
                                   'allFootnotes' : all_footnotes, 
                                   'metrics' : metrics},
            }
    period_parameters = {'allHistory' : all_history}
    if update_date:
        period_parameters['updateDate'] = update_date.isoformat()
    payload['periodParameters'] = period_parameters
    return _json_POST("mappedData", payload)

def as_reported_raw(company_identifier, 
                     statement_type, 
                     period_type='annual', 
                     all_periods=False, 
                     descending_dates=False):
    '''
    As-Reported Data.
    
    Get statements as reported by the filing company
    
    Args:
        company_identifier: a ticker or a CIK code, eg 'msft'
        statement_type: one of ('income', 'balance', 'cash', 'change-in-equity', 'comprehensive-income')
        period_type: either 'annual' or 'quarterly'
        all_periods: get all history or only the last four, True or False.
        descending_dates: return columns in oldest -> newest order.
        
    Returns:
        An object with columns and line items lists.  The columns have fiscal_period, period_start, period_end and instant values.
        The line items have label, local_name (the XBRL tag name), tree_depth (the indent amount), is_subtotal (whether or not the line item is computed from above metrics) and facts.
        The facts are in the same order as the columns and have fact_ids (an internal Calcbench ID), unit_of_measure (USD etc), effective_value (the reported value), and format_type.
         
         Example:
             {
                "entity_name": "Microsoft Corp",
                "name": "INCOME STATEMENTS",
                "period_type": 2,
                "columns": [
                            {"fiscal_period": "Y 2008",
                            "period_start": "2007-07-01",
                            "period_end": "2008-06-30",
                            "instant": false
                        },...],
                "line_items" : [
                            {"label": "Revenue",
                            "local_name": "SalesRevenueNet",
                            "tree_depth": 3,
                            "is_subtotal": false,
                            "facts": [
                                {
                                    "fact_id": 5849672,
                                    "unit_of_measure": "USD",
                                    "effective_value": 60420000000,
                                    "format_type": "currency",
                                    "text_fact_id": 5849351
                                },...]}
                    ...]
                }        
    '''
    url = _SESSION_STUFF['api_url_base'].format("asReported")
    payload = {'companyIdentifier' : company_identifier,
               'statementType' : statement_type,
               'periodType' : period_type,
               'allPeriods' : all_periods,
               'descendingDates' : descending_dates}
    response = _calcbench_session().get(url, 
                                        params=payload, 
                                        headers={'content-type' : 'application/json'}, 
                                        verify=_SESSION_STUFF['ssl_verify'])
    response.raise_for_status()
    data = response.json()
    return data
    
    
def dimensional_raw(company_identifiers=None, metrics=[], start_year=None, 
                 start_period=None, end_year=None, end_period=None, period_type='annual'):
    '''
    Breakouts
    
    Get breakouts/segments, see https://www.calcbench.com/breakout.
    
    Args:
        company_identifiers : list of tickers or CIK codes
        metrics : list of breakouts, get the list @ https://www.calcbench.com/api/availableBreakouts, pass in the "databaseName".
        start_year: first year of data to get
        start_period: first period of data to get.  0 for annual data, 1, 2, 3, 4 for quarterly data.
        end_year: last year of data to get
        end_period: last period of data to get. 0 for annual data, 1, 2, 3, 4 for quarterly data.
        period_type: quarterly or annual, only applicable when other period data not supplied.
        
    Returns:
        A list of breakout points.  The points correspond to the lines @ https://www.calcbench.com/breakout.  For each requested metric there will \
        be a the formatted value and the unformatted value denote bya  _effvalue suffix.  The label is the dimension label associated with the values.
        
        
    '''
    if len(metrics) == 0:
        raise(ValueError("Need to supply at least one breakout."))
    if period_type not in ('annual', 'quarterly'):
        raise(ValueError("period_type must be in ('annual', 'quarterly')"))

    payload = {'companiesParameters' : {'entireUniverse' : len(company_identifiers) == 0,
                                       'companyIdentifiers' : company_identifiers},
              'periodParameters' : {'year' : end_year or start_year, 
                                    'period' : start_period,
                                    'endYear' : start_year,
                                    'periodType' : period_type,
                                    'asOriginallyReported' : False},
              'pageParameters' : {'metrics' : metrics,
                                  'dimensionName' : 'Segment',
                                  'AsOriginallyReported': False}}
    return _json_POST('dimensionalData', payload)

def document_search(company_identifiers=None, 
                    full_text_search_term=None,
                    year=None, 
                    period=0, 
                    period_type=None,
                    document_type=None,
                    block_tag_name=None,
                    entire_universe=False,
                    use_fiscal_period=False,
                    document_name=None,
                    all_history=False,
                    updated_from=None,
                    batch_size=100,
                    ):        
    '''
    Footnotes and other text
    
    Search for footnotes and other , see https://www.calcbench.com/footnote.
    
    Args:
        company_identifiers : list of tickers or CIK codes
        year: Year to get data for
        period: first period of data to get.  0 for annual data, 1, 2, 3, 4 for quarterly data.
        period_type: quarterly or annual, only applicable when other period data not supplied.
        document_type: integer for Calcbench document type, Business Description:1100, Risk Factors:1110, Unresolved Comments:1120, Properties:1200, Legal Proceedings:1300, Executive Officers:2410, Defaults:2300, Market For Equity:2500, Selected Data:2600, MD&A:2700, Market Risk:2710, Auditor's Report:2810, Auditor Changes/Disagreements:2900, Controls And Procedures:2910, Other Information:2920, Corporate Governance:3100, Security Ownership:3120, Relationships:3130
        document_name: string for disclosure name, for example CommitmentAndContingencies.  Call document_types() for the whole list.
        updated_from: date, include filings from this date and after.
    Returns:
        A list of text documents
        
    '''
    if not any([full_text_search_term, document_type, block_tag_name, document_name]):
        raise(ValueError("Need to supply at least one search parameter."))
    if not (company_identifiers or entire_universe):
        raise(ValueError("Need to supply company_identifiers or entire_universe=True"))
    if not all_history:
        period_type = period_type or 'annual' if period in (0, 'Y') else 'quarterly'
    payload = {'companiesParameters' : {'entireUniverse' : entire_universe,
                                        'companyIdentifiers' : company_identifiers,
                                        },
               'periodParameters' : {'year' : year,
                                     'period' : period,
                                     'periodType' : period_type,
                                     'useFiscalPeriod' : use_fiscal_period,
                                     'allHistory' : all_history,
                                     'updatedFrom' : updated_from and updated_from.isoformat(), 
                                     },
               'pageParameters' : {'fullTextQuery' : full_text_search_term,
                                   'footnoteType' : document_type,
                                   'footnoteTag' : block_tag_name,
                                   'disclosureName' : document_name,
                                   'limit' : batch_size
                                   }
               }
    
    results = {'moreResults' : True}
    while results['moreResults']:
        results = _json_POST('footnoteSearch', payload)
        for result in results['footnotes']:
            yield DocumentSearchResults(result)
        payload['pageParameters']['startOffset'] = results['nextGroupStartOffset']
        
        
class DocumentSearchResults(dict):
    def get_contents(self):
        if self.get('network_id'):
            return document_contents_by_network_id(self['network_id'])
        else:            
            return document_contents(blob_id=self['blob_id'], SEC_ID=self['sec_filing_id'])
    
def document_contents(blob_id, SEC_ID, SEC_URL=None):
    url = _SESSION_STUFF['domain'].format('query/disclosureBySECLink')
    payload = {'blobid' : blob_id, 'secid' : SEC_ID, 'url' : SEC_URL}
    response = _calcbench_session().get(url,
                                        params=payload,
                                        headers={'content-type': 'application/json'},
                                        verify=_SESSION_STUFF['ssl_verify'],
                                        timeout=_SESSION_STUFF['timeout'])
    response.raise_for_status()
    return response.json()['blobs'][0]

def document_contents_by_network_id(network_id):
    url = _SESSION_STUFF['domain'].format('query/disclosureByNetworkIDOBJ')
    payload = {'nid' : network_id}
    response = _calcbench_session().get(url,
                                        params=payload,
                                        headers={'content-type': 'application/json'},
                                        verify=_SESSION_STUFF['ssl_verify'],
                                        timeout=_SESSION_STUFF['timeout'])

    response.raise_for_status()
    return response.json()['blobs'][0]

def tag_contents(accession_id, block_tag_name):
    url = _SESSION_STUFF['domain'].format('query/disclosuresByTag')
    payload = {'accession_ids' : accession_id, 'block_tag_name' : block_tag_name}
    response = _calcbench_session().get(url, 
                                        params=payload,
                                        headers={'content-type' : 'application/json'},
                                        verify=_SESSION_STUFF['ssl_verify'])
    response.raise_for_status()
    return response.json()[0]['blobs'][0]

def tickers(SIC_codes=[], index=None, company_identifiers=[], entire_universe=False):
    '''Return a list of tickers in the peer-group'''
    companies = _companies(SIC_codes, index, company_identifiers, entire_universe)
    tickers = [co['ticker'] for co in companies]
    return tickers


def companies(SIC_codes=[], index=None, company_identifiers=[], entire_universe=False, include_most_recent_filing_dates=False):
    '''Return a DataFrame with company details'''
    companies = _companies(SIC_codes, index, company_identifiers, entire_universe, include_most_recent_filing_dates)
    return pd.DataFrame(companies)
    
def _companies(SIC_code, index, company_identifiers, entire_universe=False, include_most_recent_filing_dates=False):
    if not(SIC_code or index or entire_universe or company_identifiers):
        raise ValueError('Must supply SIC_code, index or company_identifiers or entire_univers.')
    payload = {}
 
    if index:
        if index not in ("SP500", "DJIA"):
            raise ValueError("index must be either 'SP500' or 'DJIA'")
        payload['index'] = index
    elif SIC_code:
        payload['SICCodes'] = SIC_code
    elif company_identifiers:
        payload['companyIdentifiers'] = ','.join(company_identifiers)
    else:
        payload['universe'] = True
    payload['includeMostRecentFilingExtras'] = include_most_recent_filing_dates
    url = _SESSION_STUFF['api_url_base'].format("companies")
    r = _calcbench_session().get(url, params=payload, verify=_SESSION_STUFF['ssl_verify'])
    r.raise_for_status()
    return r.json()

def companies_raw(SIC_codes=[], index=None, company_identifiers=[], entire_universe=False):
    return _companies(SIC_codes, index, company_identifiers, entire_universe)

def company_disclosures(ticker, period=None, year=None, statement_type=None):    
    payload = {'companyIdentifier' : ticker}
    if period:
        payload['period'] = period
    if year:
        payload['year'] = year
    if statement_type:
        payload['statementType'] = statement_type
    url = _SESSION_STUFF['api_url_base'].format('companyDisclosures')
    r = _calcbench_session().get(url, params=payload, verify=_SESSION_STUFF['ssl_verify'])
    r.raise_for_status()
    return r.json()
                          
def disclosure_text(network_id):
    url = _SESSION_STUFF['api_url_base'].format('disclosure')
    r = _calcbench_session().get(url, params={'networkID': network_id}, verify=_SESSION_STUFF['ssl_verify'])
    r.raise_for_status()
    return r.json()

def available_metrics():
    url = _SESSION_STUFF['api_url_base'].format('availableMetrics')
    r = _calcbench_session().get(url, verify=_SESSION_STUFF['ssl_verify'])
    r.raise_for_status()
    return r.json()

def business_combinations(company_identifiers):
    payload = {
               'companiesParameters' : {'companyIdentifiers' : company_identifiers},
               'pageParameters' : {},
            }
    period_parameters = {}
    payload['periodParameters'] = period_parameters
    return _json_POST('businessCombinations', payload)

def filings(company_identifiers=[], entire_universe=False, include_non_xbrl=True, received_date=None):
    return _json_POST('filingsV2', {
                                    'companiesParameters' : {'companyIdentifiers' : list(company_identifiers), 'entireUniverse' : entire_universe},
                                    'pageParameters' : {'includeNonXBRL' : include_non_xbrl},
                                    'periodParameters' : {'updateDate' : received_date and received_date.isoformat()},
                                    })
    
def document_types():
    url = _SESSION_STUFF['api_url_base'].format('documentTypes')
    r = _calcbench_session().get(url, verify=_SESSION_STUFF['ssl_verify'])
    r.raise_for_status()
    return r.json()

def html_diff(html_1, html_2):
    '''Diff two pieces of html and return a html diff'''
    return _json_POST('textDiff', {'html1': html_1,
                                   'html2': html_2
                                   })
if __name__ == '__main__':
    print(html_diff('some html', 'some other html'))

