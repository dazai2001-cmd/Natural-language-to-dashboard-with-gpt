import os
import re
import json
import inspect
import streamlit as st
import pandas as pd
import plotly.express as px
from typing import Any, Optional, Dict, Callable, TypeVar
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_community.callbacks.streamlit.streamlit_callback_handler import \
    StreamlitCallbackHandler
from langchain_core.globals import set_llm_cache
from langchain_community.chat_models import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain.chains import create_sql_query_chain
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from streamlit.runtime.scriptrunner import (add_script_run_ctx,
                                            get_script_run_ctx)
from langchain_core.caches import InMemoryCache

load_dotenv()

set_llm_cache(InMemoryCache())


class DatabaseAssistant:
    def __init__(self, model, db):
        self.model = model
        self.db = db
        self.setup_prompts()

    def create_data_transform_prompt(self):
        base_prompt = """You are a data transformation expert. Transform the SQL query result into the exact format needed for a {chart_type} chart.

          SQL Query Result: {result}

          Your response must be a valid JSON object containing ONLY the chart_data field with the exact structure shown in the example.
        """

        chart_prompts = {
            "bar": """For a bar chart, return JSON in this EXACT format:
              {{
                  "chart_data": {{
                      "labels": ["Category1", "Category2", ...],
                      "values": [
                          {{
                              "data": [number1, number2, ...],
                              "label": "Metric Name"
                          }}
                      ]
                  }}
              }}

              Example with SQL: "SELECT source_system_name, COUNT(*) as count FROM customer GROUP BY source_system_name"
              {{
                  "chart_data": {{
                      "labels": ["System A", "System B", "System C"],
                      "values": [
                          {{
                              "data": [45, 32, 28],
                              "label": "Customer Count"
                          }}
                      ]
                  }}
              }}

              Example with multiple series:
              {{
                  "chart_data": {{
                      "labels": ["NSW", "VIC", "QLD"],
                      "values": [
                          {{
                              "data": [500000, 750000, 450000],
                              "label": "Total Customers"
                          }},
                          {{
                              "data": [35, 30, 28],
                              "label": "Average Age"
                          }}
                      ]
                  }}
              }}""",

            "horizontal_bar": """For a horizontal bar chart, return JSON in this EXACT format:
              {{
                  "chart_data": {{
                      "labels": ["Category1", "Category2", ...],
                      "values": [
                          {{
                              "data": [number1, number2, ...],
                              "label": "Metric Name"
                          }}
                      ]
                  }}
              }}

              Example:
              {{
                  "chart_data": {{
                      "labels": ["Male", "Female"],
                      "values": [
                          {{
                              "data": [75000, 78000],
                              "label": "Customer Count"
                          }}
                      ]
                  }}
              }}""",

            "line": """For a line chart, return JSON in this EXACT format:
              {{
                  "chart_data": {{
                      "xValues": ["2023-01", "2023-02", ...],
                      "yValues": [
                          {{
                              "data": [number1, number2, ...],
                              "label": "Metric Name"
                          }}
                      ]
                  }}
              }}

              Example:
              {{
                  "chart_data": {{
                      "xValues": ["2023-01", "2023-02", "2023-03", "2023-04"],
                      "yValues": [
                          {{
                              "data": [12500, 13600, 14800, 15200],
                              "label": "Monthly Registrations"
                          }}
                      ]
                  }}
              }}

              Example with multiple series:
              {{
                  "chart_data": {{
                      "xValues": ["2023-01", "2023-02", "2023-03"],
                      "yValues": [
                          {{
                              "data": [5000, 5500, 6000],
                              "label": "System A Customers"
                          }},
                          {{
                              "data": [4000, 4200, 4500],
                              "label": "System B Customers"
                          }}
                      ]
                  }}
              }}""",

            "pie": """For a pie chart, return JSON in this EXACT format:
              {{
                  "chart_data": [
                      {{
                          "value": number,
                          "label": "Category Name"
                      }}
                  ]
              }}

              Example:
              {{
                  "chart_data": [
                      {{
                          "value": 150,
                          "label": "System A"
                      }},
                      {{
                          "value": 45,
                          "label": "System B"
                      }},
                      {{
                          "value": 25,
                          "label": "System C"
                      }}
                  ]
              }}""",

            "scatter": """For a scatter plot, return JSON in this EXACT format:
              {{
                  "chart_data": {{
                      "series": [
                          {{
                              "data": [
                                  {{
                                      "x": number,
                                      "y": number,
                                      "id": number
                                  }}
                              ],
                              "label": "Series Name"
                          }}
                      ]
                  }}
              }}

              Example:
              {{
                  "chart_data": {{
                      "series": [
                          {{
                              "data": [
                                  {{
                                      "x": -33.865,
                                      "y": 151.209,
                                      "id": 1
                                  }},
                                  {{
                                      "x": -37.813,
                                      "y": 144.963,
                                      "id": 2
                                  }},
                                  {{
                                      "x": -27.470,
                                      "y": 153.021,
                                      "id": 3
                                  }}
                              ],
                              "label": "Customer Locations"
                          }}
                      ]
                  }}
              }}

              Example with multiple series:
              {{
                  "chart_data": {{
                      "series": [
                          {{
                              "data": [
                                  {{
                                      "x": -33.865,
                                      "y": 151.209,
                                      "id": 1
                                  }},
                                  {{
                                      "x": -37.813,
                                      "y": 144.963,
                                      "id": 2
                                  }}
                              ],
                              "label": "Male Customers"
                          }},
                          {{
                              "data": [
                                  {{
                                      "x": -27.470,
                                      "y": 153.021,
                                      "id": 3
                                  }},
                                  {{
                                      "x": -31.950,
                                      "y": 115.860,
                                      "id": 4
                                  }}
                              ],
                              "label": "Female Customers"
                          }}
                      ]
                  }}
              }}"""
        }

        bar_prompt = base_prompt + chart_prompts.get("bar")
        horizontal_bar_prompt = base_prompt + \
            chart_prompts.get("horizontal_bar")
        pie_prompt = base_prompt + chart_prompts.get("pie")
        scatter_prompt = base_prompt + chart_prompts.get("scatter")
        line_prompt = base_prompt + chart_prompts.get("line")

        return (
            PromptTemplate.from_template(bar_prompt),
            PromptTemplate.from_template(horizontal_bar_prompt),
            PromptTemplate.from_template(pie_prompt),
            PromptTemplate.from_template(scatter_prompt),
            PromptTemplate.from_template(line_prompt)
        )

    def setup_prompts(self):
        self.sql_prompt = PromptTemplate.from_template("""
            You are a SQL expert with access to a BigQuery dataset containing customers and customer addresses.
            Given an input question, generate a syntactically correct SQL query to answer it. Unless explicitly requested otherwise, limit the results to {top_k} rows.

            Relevant Table Information:
            {table_info}

            Question: {input}

            Guidelines:
            1. Ensure that all attribute searches are case-insensitive.
            2. ALWAYS add 'LIMIT {top_k}' at the end of the query unless:
              - The question explicitly asks for all records
              - The query uses GROUP BY and needs to show all groups
              - The query is counting records (using COUNT)
              - The query calculates aggregates that need all data

            Address and Location Queries:
            1. For questions about addresses, locations, or properties, always include latitude and longitude columns in the SELECT clause.

            Double check the user's postgresql query for common mistakes, including:
            - Using NOT IN with NULL values
            - Using UNION when UNION ALL should have been used
            - Using BETWEEN for exclusive ranges
            - Data type mismatch in predicates
            - Properly quoting identifiers
            - Using the correct number of arguments for functions
            - Casting to the correct data type
            - Using the proper columns for joins
            - Missing LIMIT clause when returning raw records

            If there are any of the above mistakes, rewrite the query.
            If there are no mistakes, just reproduce the original query with no further commentary.

            Provide only the final SQL query as plain text without any formatting.
            If the question is not about customers or addresses, respond with "I don't know"
            """)

        self.viz_prompt = PromptTemplate.from_template(
            """You are an AI assistant that recommends appropriate data visualizations for customer and address analytics. Based on the user's question, SQL query, and query results, suggest the most suitable type of graph or chart to visualize the data.

                Available chart types and their best use cases:

                - Bar Graphs (for 3+ categories): 
                  * Comparing distributions across multiple categories
                  * Customer counts by source system
                  * Customer demographics across regions/states
                  * Age group distributions
                  * Monthly/yearly registration counts

                - Horizontal Bar Graphs (for 2-3 categories or large value disparities):
                  * Binary comparisons (e.g., gender distribution)
                  * Limited category comparisons (2-3 items)
                  * Cases with large value differences between categories

                - Line Graphs (for time series only):
                  * Customer registration trends over time
                  * Growth patterns by source system
                  * Any metric tracked over time periods
                  Note: X-axis MUST represent time (create_timestamp or similar)

                - Pie Charts (for proportions, 3-7 categories max):
                  * Distribution percentages
                  * Market share analysis
                  * Proportional comparisons
                  Note: Total should sum to 100%

                - Scatter Plots (for numeric relationships):
                  * Age vs other numeric metrics
                  * Timestamp patterns
                  * Distribution analysis
                  Note: Both axes must be numeric, non-categorical

                Special Cases:
                1. Geographic Data:
                  * If result contains latitude and longitude → No chart (will display map)
                  * For address/location questions → No chart (will display map)

                2. Raw Data:
                  * Individual customer records → No chart (tabular display)
                  * Non-aggregated data → No chart (tabular display)

                Tables in scope:
                - customer: customer_key, first_name, last_name, source_system_name, dob, gender, create_timestamp
                - customer_address: customer_key, address_key
                - address: address_key, full_address, state, country, latitude, longitude

                Question: {question}
                SQL Query: {query}
                SQL Result: {result}

                Provide your response in the following format:
                Recommended Visualization: [Chart type or "None"]. ONLY use the following names: bar, horizontal_bar, line, pie, scatter, none
                Reason: [Brief explanation for your recommendation]
                """)

        self.create_answer_prommpt = PromptTemplate.from_template(
            """Given the following user question, corresponding SQL query, and SQL result, answer the user question.

              Question: {question}
              SQL Query: {query}
              SQL Result: {result}
              Answer: """
        )
        self.bar_prompt, self.horizontal_bar_prompt, self.pie_prompt, self.scatter_prompt, self.line_prompt = self.create_data_transform_prompt()

    def convert_dates(self, obj):
        response_str = re.sub(
            r'datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)', r"'\1-\2-\3'", obj)
        response_str = re.sub(r'datetime\.datetime\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*(\d+))?\)',
                              r"'\1-\2-\3 \4:\5:\6.\7'", response_str)
        return response_str

    def suggest_visualization(self, result: str) -> str:
        if result.startswith("Error") or result == "I don't know":
            return None

        chain = self.viz_prompt | self.model | StrOutputParser()
        return chain.invoke({"result": result})

    # Extract latitude and longitude coordinates from query results.
    def extract_coordinates(self, result: dict) -> Optional[dict]:
        try:
            if isinstance(result, dict):
                if "result" in result:
                    result = result["result"]
                    if isinstance(result, dict) and "result" in result:
                        result_str = result["result"]
                    else:
                        result_str = str(result)
                else:
                    return None
            else:
                return None

            try:
                if isinstance(result_str, str):
                    result_data = eval(result_str)
                else:
                    result_data = result_str
            except Exception as e:
                print(f"Error evaluating result string: {e}")
                return None

            if not isinstance(result_data, list):
                return None

            unique_lat_values = set()
            unique_long_values = set()

            for row in result_data:
                if isinstance(row, dict):
                    if 'latitude' in row and row['latitude'] is not None:
                        try:
                            unique_lat_values.add(float(row['latitude']))
                        except (ValueError, TypeError):
                            pass

                    if 'longitude' in row and row['longitude'] is not None:
                        try:
                            unique_long_values.add(float(row['longitude']))
                        except (ValueError, TypeError):
                            pass

            if unique_lat_values and unique_long_values:
                return {
                    "latitude": list(unique_lat_values),
                    "longitude": list(unique_long_values)
                }
            return None

        except Exception as e:
            print(f"Error extracting coordinates: {e}")
            return None

    # Generate SQL query and execute
    def process_query_chain(self):

        text_to_sql = create_sql_query_chain(
            self.model, self.db, self.sql_prompt)

        @RunnableLambda
        def handle_dont_know(result, config):
            dispatch_custom_event(
                "process.is_complete",
                {
                    "status": True
                },
                config=config
            )
            if isinstance(result, dict) and result.get("query") == "I don't know":
                return result.get("query")
            return result

        @RunnableLambda
        def execute_query(result, config):
            dispatch_custom_event(
                "process.execute_query",
                {
                    "status": ""
                },
                config=config
            )
            return {
                **result,
                'result': self.convert_dates(
                    self.db.run_no_throw(
                        command=result["query"], include_columns=True)
                )
            }

        @RunnableLambda
        def transform_data_for_visualization_chain(args, config):
            try:
                dispatch_custom_event(
                    "process.transform_data_for_visualization_chain",
                    {
                        "status": ""
                    },
                    config=config
                )
                chart_type = args.get("visualization").get("type")
                result = args.get("result")

                if not chart_type or not result:
                    return {"chart_data": None}

                if chart_type == 'bar':
                    transform_prompt = self.bar_prompt
                elif chart_type == 'horizontal_bar':
                    transform_prompt = self.horizontal_bar_prompt
                elif chart_type == 'pie':
                    transform_prompt = self.pie_prompt
                elif chart_type == 'scatter':
                    transform_prompt = self.scatter_prompt
                elif chart_type == 'line':
                    transform_prompt = self.line_prompt
                else:
                    transform_prompt = None

                assign_chart_type_and_result = RunnableLambda(
                    lambda args: {**args, "chart_type": args.get("visualization", {}).get(
                        "type"), "result": args.get("result")}
                )

                if transform_prompt:
                    transform_chain = (
                        assign_chart_type_and_result
                        | transform_prompt
                        | self.model
                    )
                    return transform_chain

                return {"chart_data": None}

            except Exception as e:
                print(e)
                print(f"Error in transform_data_for_visualization: {e}")
                return {"chart_data": None}

        # Format the final result including answer, coordinates, and chart data.
        @RunnableLambda
        def format_final_result(result, config):
            try:
                dispatch_custom_event(
                    "process.format_final_result",
                    {
                        "status": ""
                    },
                    config=config
                )
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        result = {"answer": result}

                answer = ""
                chart_data = None
                chart_type = None
                coordinates = None

                # Extract chart data from AIMessage
                if isinstance(result, dict):
                    coordinates = result.get("coordinates")

                    # Get chart type from visualization
                    visualization = result.get('visualization', {})
                    if isinstance(visualization, dict):
                        chart_type = visualization.get('type')

                    chart_data_msg = result.get('chart_data')
                    if hasattr(chart_data_msg, 'content'):
                        try:
                            content = chart_data_msg.content
                            content = content.replace(
                                '```json', '').replace('```', '').strip()
                            parsed_data = json.loads(content)
                            if isinstance(parsed_data, dict) and 'chart_data' in parsed_data:
                                chart_data = parsed_data['chart_data']
                        except json.JSONDecodeError:
                            print("Failed to parse chart data JSON")
                            chart_data = None

                    answer_msg = result.get('answer')

                    if hasattr(answer_msg, 'content'):
                        answer = answer_msg.content
                    elif isinstance(answer_msg, str):
                        answer = answer_msg
                    elif isinstance(answer_msg, dict) and 'content' in answer_msg:
                        answer = answer_msg['content']
                    else:
                        result_data = result.get("result", {})
                        if isinstance(result_data, dict) and "result" in result_data:
                            answer = str(result_data["result"])
                        else:
                            answer = str(result_data)

                response_dict = {
                    "answer": answer,
                    "coordinates": coordinates,
                    "chart_data": chart_data,
                    "chart_type": chart_type
                }
                return json.dumps(response_dict)

            except Exception as e:
                print(f"Error in format_final_result: {e}")
                return json.dumps({
                    "answer": "Error formatting result",
                    "coordinates": None,
                    "chart_data": None,
                    "chart_type": None
                })

        @RunnableLambda
        def parse_visualization_response(data, config):
            try:
                dispatch_custom_event(
                    "process.parse_visualization_response",
                    {
                        "status": ""
                    },
                    config=config
                )
                response = data.content if hasattr(
                    data, 'content') else str(data)
                viz_text = response.content if hasattr(
                    response, 'content') else str(response)

                viz_lines = [line.strip()
                             for line in viz_text.split('\n') if line.strip()]

                chart_type = None
                reason = None

                for line in viz_lines:
                    if 'Recommended Visualization:' in line:
                        chart_type = line.split('Recommended Visualization:')[
                            1].strip().lower()
                    elif 'Reason:' in line:
                        reason = line.split('Reason:')[1].strip()

                print(f"Chart Type: {chart_type}, Reason: {reason}")
                return {"type": chart_type, "reason": reason}

            except Exception as e:
                print(f"Error parsing visualization response: {e}")
                return {"type": "none", "reason": "Error parsing visualization response"}

        chain = (
            RunnablePassthrough().assign(query=text_to_sql)
            | RunnablePassthrough().assign(
                result=execute_query
            )
            | RunnablePassthrough().assign(
                coordinates=lambda x: self.extract_coordinates(x)
            )
            | RunnablePassthrough.assign(
                visualization=RunnableLambda(
                    lambda x: {
                        "question": x.get("question", ""),
                        "query": x["query"],
                        "result": x.get("result", {}).get("result")
                    }
                )
                | self.viz_prompt
                | self.model
                | parse_visualization_response
            )
            | RunnablePassthrough().assign(
                chart_data=transform_data_for_visualization_chain
            )
            | RunnablePassthrough.assign(
                answer=self.create_answer_prommpt | self.model
            )
            | format_final_result
            | handle_dont_know
            | StrOutputParser()
        )

        return chain


class CustomStreamlitCallbackHandler(StreamlitCallbackHandler):
    def on_custom_event(self, name: str, data: dict, **kwargs):
        """Handle custom events, update labels, and mark as complete if specified."""
        if self._current_thought is not None:
            custom_event_label = f"💡{name}"
            self._current_thought.container.update(
                new_label=custom_event_label)

            content = f"**{name}:** {data}"
            self._current_thought.container.markdown(content)

            is_complete = data.get("is_complete", False)
            if is_complete or name == "process.completed":
                complete_label = f"✅ Complete, awaiting response"
                self._current_thought.complete(final_label=complete_label)
        else:
            st.write(f"Custom Event Triggered Outside Thought Context: {data}")

    def on_llm_end(self, response, **kwargs):
        """Override to ensure the label updates on LLM completion."""
        super().on_llm_end(response, **kwargs)
        if self._current_thought:
            self._current_thought.complete(
                final_label="✅ Complete, awaiting response")

    def on_tool_end(self, output, **kwargs):
        """Override to ensure the label updates on tool completion."""
        super().on_tool_end(output, **kwargs)
        if self._current_thought:
            self._current_thought.complete(final_label="✅ Tool Complete")


def initialize_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Hey there👋 I'm your friendly database assistant. Got data that needs decoding or mysteries to unravel? Let's dive in!"}
        ]


def process_query(question: str, assistant: DatabaseAssistant) -> Dict[str, Any]:
    try:
        chain = assistant.process_query_chain()
        return chain.stream(
            {"question": question, "top_k": 10},
            {"callbacks": [get_streamlit_cb(st.container())]}
        )

    except Exception as e:
        st.error(f"Error processing query: {str(e)}")
        return {"answer": "Sorry, I encountered an error processing your query.", "chart_data": None, "chart_type": None}


def display_visualization(response: Dict[str, Any]):
    if chart_data := response.get("chart_data"):
        chart_type = response.get("chart_type")
        try:
            if chart_type == "bar":
                df = pd.DataFrame({
                    'Category': chart_data['labels'],
                    'Value': chart_data['values'][0]['data']
                })
                st.bar_chart(df.set_index('Category'))

            elif chart_type == "line":
                df = pd.DataFrame({
                    'Date': chart_data['xValues'],
                    'Value': chart_data['yValues'][0]['data']
                })
                st.line_chart(df.set_index('Date'))

            elif chart_type == "pie":
                df = pd.DataFrame(chart_data)
                if not df.empty and 'value' in df.columns and 'label' in df.columns:
                    fig = px.pie(df, values='value',
                                 names='label', title='Distribution')
                    st.plotly_chart(fig)

            elif chart_type == "scatter":
                df = pd.DataFrame(chart_data['series'][0]['data'])
                st.scatter_chart(data=df, x='x', y='y')

        except Exception as e:
            st.warning(f"Could not display chart: {str(e)}")

    if coordinates := response.get("coordinates"):
        try:
            df = pd.DataFrame({
                'latitude': coordinates['latitude'],
                'longitude': coordinates['longitude']
            })
            st.map(df)
        except Exception as e:
            st.warning(f"Could not display map: {str(e)}")


def get_streamlit_cb(parent_container):
    try:
        fn_return_type = TypeVar('fn_return_type')

        def add_streamlit_context(fn: Callable[..., fn_return_type]) -> Callable[..., fn_return_type]:
            ctx = get_script_run_ctx()

            def wrapper(*args, **kwargs) -> fn_return_type:
                add_script_run_ctx(ctx=ctx)
                return fn(*args, **kwargs)

            return wrapper

        st_cb = CustomStreamlitCallbackHandler(
            parent_container, collapse_completed_thoughts=True)

        for method_name, method_func in inspect.getmembers(st_cb, predicate=inspect.ismethod):
            if method_name.startswith('on_'):
                setattr(st_cb, method_name, add_streamlit_context(method_func))
        return st_cb
    except Exception as e:
        st.error(f"Error setting up callback handler: {str(e)}")
        return None


def handle_stream_response(response_chunk, messages):
    """Handle streaming response chunks."""
    try:
        # Try to parse as JSON first
        if isinstance(response_chunk, str):
            try:
                chunk_dict = json.loads(response_chunk)
                answer = chunk_dict.get("answer", "")

                st.write(answer)
                display_visualization(chunk_dict)

                messages.append(
                    {"role": "assistant", "content": response_chunk})
            except json.JSONDecodeError:
                st.write(response_chunk)
                messages.append(
                    {"role": "assistant", "content": response_chunk})
        else:
            st.write(str(response_chunk))
            messages.append(
                {"role": "assistant", "content": str(response_chunk)})

    except Exception as e:
        st.error(f"Error handling stream response: {e}")
        messages.append({"role": "assistant", "content": str(response_chunk)})


def main():
    st.set_page_config(page_title="Database Assistant", page_icon="🤖")
    initialize_session_state()

    service_account_file = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    project = os.environ["GOOGLE_PROJECT"]
    dataset = os.environ["BIGQUERY_DATASET"]

    sql_url = (
        f"bigquery://{project}/{dataset}?credentials_path={service_account_file}"
    )

    db = SQLDatabase.from_uri(sql_url)

    model = ChatOpenAI(model="gpt-4o-mini", temperature=0,
                       max_tokens="10000", timeout=30000, verbose=True)

    assistant = DatabaseAssistant(model, db)

    # Process a query
    # chain = assistant.process_query_chain()
    # response = chain.invoke(
    #     {"question": "how many customers from each source", "top_k": 10})
    # print(response)

    st.title("🐙 Database Assistant")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if isinstance(message["content"], dict):
                st.write(message["content"]["answer"])
                display_visualization(message["content"])
            else:
                st.write(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask about your data..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        with st.chat_message("assistant"):
            response = process_query(prompt, assistant)
            # st.write(response["answer"])
            # display_visualization(response)
            if response is not None:
                for chunk in response:
                    handle_stream_response(
                        chunk, st.session_state.messages)

        st.session_state.messages.append(
            {"role": "assistant", "content": response})


if __name__ == "__main__":
    if 'initialized' not in st.session_state:
        set_llm_cache(InMemoryCache())
        st.session_state.initialized = True

    main()
