"""
Streamlit UI for Recruiting Database Assistant
Chat-based interface for recruiters to query candidate database
"""

import streamlit as st
import pandas as pd
from datetime import datetime
from main import get_agent, DatabaseManager
import json

# Page configuration
st.set_page_config(
    page_title="Recruiting Database Assistant",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .chat-message {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
        border-left: 5px solid;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left-color: #1976d2;
    }
    .agent-message {
        background-color: #f3e5f5;
        border-left-color: #7b1fa2;
    }
    .error-message {
        background-color: #ffebee;
        border-left-color: #c62828;
    }
    .sql-query {
        background-color: #f5f5f5;
        padding: 0.5rem;
        border-radius: 0.25rem;
        font-family: monospace;
        font-size: 0.9rem;
        margin: 0.5rem 0;
    }
    .stats-box {
        background-color: #e8f5e9;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

if 'query_count' not in st.session_state:
    st.session_state.query_count = 0

if 'agent' not in st.session_state:
    try:
        st.session_state.agent = get_agent()
        st.session_state.agent_initialized = True
    except Exception as e:
        st.session_state.agent_initialized = False
        st.session_state.init_error = str(e)


def format_chat_message(message_type: str, content: str, data=None, sql_query=None, message_id=None):
    """Format a chat message with appropriate styling"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Generate unique ID for this message if not provided
    if message_id is None:
        message_id = f"{message_type}_{timestamp}_{hash(content) % 10000}"
    
    if message_type == "user":
        st.markdown(f"""
        <div class="chat-message user-message">
            <strong>👤 You</strong> <small>({timestamp})</small><br/>
            {content}
        </div>
        """, unsafe_allow_html=True)
    
    elif message_type == "agent":
        st.markdown(f"""
        <div class="chat-message agent-message">
            <strong>🤖 Agent</strong> <small>({timestamp})</small><br/>
            {content}
        </div>
        """, unsafe_allow_html=True)
        
        if sql_query:
            st.markdown(f"""
            <div class="sql-query">
                <strong>Generated SQL:</strong><br/>
                <code>{sql_query}</code>
            </div>
            """, unsafe_allow_html=True)
        
        if data and len(data) > 0:
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            
            # Option to download results with unique key
            csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download Results as CSV",
                data=csv,
                file_name=f"candidates_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                key=f"download_{message_id}"  # Unique key for each download button
            )
    
    elif message_type == "error":
        st.markdown(f"""
        <div class="chat-message error-message">
            <strong>⚠️ Error</strong> <small>({timestamp})</small><br/>
            {content}
        </div>
        """, unsafe_allow_html=True)


def display_stats():
    """Display database statistics in the sidebar"""
    try:
        db = DatabaseManager()
        count_result = db.execute_query("SELECT COUNT(*) as total FROM candidates")
        
        if count_result.success:
            total_candidates = count_result.data[0]['total']
            
            st.sidebar.markdown(f"""
            <div class="stats-box">
                <h3 style="margin: 0; color: #2e7d32;">📊 Database Stats</h3>
                <h2 style="margin: 0.5rem 0; color: #1b5e20;">{total_candidates}</h2>
                <p style="margin: 0; color: #558b2f;">Total Candidates</p>
            </div>
            """, unsafe_allow_html=True)
    except Exception as e:
        st.sidebar.error(f"Could not fetch stats: {str(e)}")


def display_sample_queries():
    """Display sample queries in the sidebar"""
    st.sidebar.markdown("### 💡 Sample Queries")
    
    sample_queries = [
        "Show me candidates with AWS experience",
        "Find candidates with more than 5 years of experience in Java",
        "List all candidates from Delhi",
        "Who knows Spring Boot?",
        "Find Python developers with AWS skills",
        "Show candidates based in Mumbai or Bangalore",
        "List all candidates with their emails"
    ]
    
    for query in sample_queries:
        if st.sidebar.button(query, key=f"sample_{query}", use_container_width=True):
            process_query(query)


def display_recent_queries():
    """Display recent queries in the sidebar"""
    if st.session_state.chat_history:
        st.sidebar.markdown("### 📜 Recent Queries")
        
        # Show last 5 queries
        recent = [msg for msg in st.session_state.chat_history if msg['type'] == 'user'][-5:]
        
        for i, msg in enumerate(reversed(recent)):
            st.sidebar.markdown(f"{i+1}. {msg['content'][:50]}...")


def process_query(query: str):
    """Process a user query through the agent"""
    if not query.strip():
        st.warning("Please enter a query")
        return
    
    # Add user message to chat history
    st.session_state.chat_history.append({
        'type': 'user',
        'content': query,
        'timestamp': datetime.now()
    })
    
    st.session_state.query_count += 1
    
    # Process query with agent
    with st.spinner("🤔 Thinking..."):
        try:
            result = st.session_state.agent.process_query(query)
            
            if result['success']:
                response_content = f"Found {len(result['data'])} candidate(s) matching your query."
                
                st.session_state.chat_history.append({
                    'type': 'agent',
                    'content': response_content,
                    'data': result['data'],
                    'sql_query': result['sql_query'],
                    'timestamp': datetime.now()
                })
            else:
                error_msg = result.get('error') or result.get('message', 'Unknown error')
                st.session_state.chat_history.append({
                    'type': 'error',
                    'content': error_msg,
                    'timestamp': datetime.now()
                })
        
        except Exception as e:
            st.session_state.chat_history.append({
                'type': 'error',
                'content': f"System error: {str(e)}",
                'timestamp': datetime.now()
            })


# Main UI
def main():
    # Header
    st.markdown('<h1 class="main-header">🧠 Recruiting Database Assistant</h1>', unsafe_allow_html=True)
    
    # Check if agent is initialized
    if not st.session_state.agent_initialized:
        st.error(f"⚠️ Failed to initialize agent: {st.session_state.get('init_error', 'Unknown error')}")
        st.info("Please check your .env file configuration (OpenAI API key and MySQL credentials)")
        return
    
    # Sidebar
    with st.sidebar:
        st.title("🎯 Navigation")
        
        display_stats()
        
        st.markdown("---")
        
        display_sample_queries()
        
        st.markdown("---")
        
        display_recent_queries()
        
        st.markdown("---")
        
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.chat_history = []
            st.session_state.query_count = 0
            st.rerun()
        
        st.markdown("---")
        st.markdown("### ℹ️ About")
        st.markdown("""
        This AI agent helps recruiters query a candidate database using natural language.
        
        **Features:**
        - Natural language to SQL conversion
        - Safe query validation
        - Real-time results
        - Export to CSV
        """)
    
    # Main chat area
    st.markdown("### 💬 Chat with the Agent")
    st.markdown("Ask questions about candidates in natural language")
    
    # Display chat history
    chat_container = st.container()
    with chat_container:
        for idx, message in enumerate(st.session_state.chat_history):
            # Generate unique message ID using index
            msg_id = f"msg_{idx}_{message['timestamp'].strftime('%H%M%S%f')}"
            
            if message['type'] == 'user':
                format_chat_message('user', message['content'], message_id=msg_id)
            elif message['type'] == 'agent':
                format_chat_message(
                    'agent',
                    message['content'],
                    data=message.get('data'),
                    sql_query=message.get('sql_query'),
                    message_id=msg_id
                )
            elif message['type'] == 'error':
                format_chat_message('error', message['content'], message_id=msg_id)
    
    # Query input
    st.markdown("---")
    
    col1, col2 = st.columns([5, 1])
    
    with col1:
        query_input = st.text_input(
            "Your query:",
            placeholder="e.g., Show me candidates with AWS experience",
            label_visibility="collapsed",
            key="query_input"
        )
    
    with col2:
        submit_button = st.button("🚀 Submit", use_container_width=True, type="primary")
    
    # Process query on button click or Enter
    if submit_button and query_input:
        process_query(query_input)
        st.rerun()
    
    # Footer stats
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Queries", st.session_state.query_count)
    with col2:
        st.metric("Chat Messages", len(st.session_state.chat_history))
    with col3:
        if st.session_state.chat_history:
            last_query = st.session_state.chat_history[-1]
            st.metric("Last Query", last_query['timestamp'].strftime("%H:%M:%S"))


if __name__ == "__main__":
    main()