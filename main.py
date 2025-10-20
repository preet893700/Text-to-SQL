import os
import json
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

# Load environment variables
load_dotenv()


class LLMManager:
    """Manages multiple LLM providers with automatic fallback"""
    
    def __init__(self):
        # Get API keys from environment
        self.openai_key = os.getenv('OPENAI_API_KEY')
        self.gemini_key = os.getenv('GEMINI_API_KEY')
        
        # Initialize clients
        self.openai_client = None
        self.gemini_client = None
        
        if self.openai_key:
            try:
                self.openai_client = OpenAI(api_key=self.openai_key)
            except Exception as e:
                print(f"OpenAI initialization failed: {e}")
        
        if self.gemini_key:
            try:
                genai.configure(api_key=self.gemini_key)
                self.gemini_client = genai.GenerativeModel('gemini-2.5-flash')
            except Exception as e:
                print(f"Gemini initialization failed: {e}")
        
        # Track which provider is currently active
        self.current_provider = "openai" if self.openai_client else "gemini"
    
    def generate_completion(self, system_prompt: str, user_query: str) -> str:
        """
        Generate completion with automatic fallback
        Tries OpenAI first, falls back to Gemini on error
        """
        # Try OpenAI first
        if self.openai_client:
            try:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_query}
                    ],
                    temperature=0.1,
                    max_tokens=500
                )
                self.current_provider = "openai"
                return response.choices[0].message.content.strip()
            
            except Exception as e:
                print(f"OpenAI API failed: {e}. Trying Gemini...")
        
        # Fallback to Gemini
        if self.gemini_client:
            try:
                # Combine system prompt and user query for Gemini
                full_prompt = f"{system_prompt}\n\nUser Query: {user_query}"
                response = self.gemini_client.generate_content(full_prompt)
                self.current_provider = "gemini"
                return response.text.strip()
            
            except Exception as e:
                print(f"Gemini API failed: {e}")
                raise Exception("Both OpenAI and Gemini APIs failed")
        
        raise Exception("No LLM provider available")
    
    def get_current_provider(self) -> str:
        """Return which provider is currently being used"""
        return self.current_provider


@dataclass
class QueryResult:
    """Structure for database query results"""
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    sql_query: Optional[str] = None


class DatabaseManager:
    """Manages MySQL database connections and query execution"""
    
    def __init__(self):
        self.config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', 3306)),
            'user': os.getenv('DB_USER', 'root'),
            'password': os.getenv('DB_PASSWORD', ''),
            'database': os.getenv('DB_NAME', 'recruiting_db')
        }
    
    def get_connection(self):
        """Create and return a database connection"""
        try:
            connection = mysql.connector.connect(**self.config)
            return connection
        except Error as e:
            print(f"Error connecting to MySQL: {e}")
            return None
    
    def execute_query(self, sql_query: str) -> QueryResult:
        """Execute a SQL query and return results"""
        connection = None
        cursor = None
        
        try:
            connection = self.get_connection()
            if not connection:
                return QueryResult(
                    success=False,
                    error="Failed to connect to database"
                )
            
            cursor = connection.cursor(dictionary=True)
            cursor.execute(sql_query)
            
            results = cursor.fetchall()
            
            return QueryResult(
                success=True,
                data=results,
                sql_query=sql_query
            )
            
        except Error as e:
            return QueryResult(
                success=False,
                error=f"Database error: {str(e)}",
                sql_query=sql_query
            )
        
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
    
    def get_table_schema(self) -> str:
        """Get the schema information for the candidates table"""
        schema_query = "DESCRIBE candidates;"
        result = self.execute_query(schema_query)
        
        if result.success:
            schema_info = "Candidates Table Schema:\n"
            for row in result.data:
                schema_info += f"- {row['Field']}: {row['Type']}\n"
            return schema_info
        
        return "Unable to retrieve schema"


class SQLValidator:
    """Validates SQL queries for safety and correctness"""
    
    @staticmethod
    def is_safe_query(sql_query: str) -> tuple[bool, str]:
        """
        Validate that the SQL query is safe to execute
        Returns: (is_valid, error_message)
        """
        sql_upper = sql_query.upper().strip()
        
        # Check for SELECT only
        if not sql_upper.startswith('SELECT'):
            return False, "Only SELECT queries are allowed"
        
        # Check for dangerous keywords
        dangerous_keywords = [
            'DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER',
            'CREATE', 'TRUNCATE', 'REPLACE', 'GRANT', 'REVOKE'
        ]
        
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                return False, f"Dangerous keyword '{keyword}' detected"
        
        # Check for multiple statements (prevent SQL injection)
        if ';' in sql_query.rstrip(';'):
            return False, "Multiple SQL statements not allowed"
        
        # Verify table name is 'candidates'
        if 'FROM' in sql_upper:
            from_match = re.search(r'FROM\s+(\w+)', sql_upper)
            if from_match:
                table_name = from_match.group(1)
                if table_name != 'CANDIDATES':
                    return False, f"Invalid table name: {table_name}. Only 'candidates' table is allowed"
        
        return True, ""


class RecruitingAgent:
    """Main agentic AI system for recruiting database queries"""
    
    def __init__(self):
        self.llm_manager = LLMManager()
        self.db_manager = DatabaseManager()
        self.validator = SQLValidator()
        self.conversation_history = []
        
        # Get database schema for context
        self.schema_info = self.db_manager.get_table_schema()
    
    def get_system_prompt(self) -> str:
        """Define the agent's system prompt"""
        return f"""You are a Recruiting Database Expert Agent. Your role is to help recruiters query a candidate database using natural language.

Database Schema:
{self.schema_info}

Your responsibilities:
1. Convert natural language to SELECT SQL queries on 'candidates' table
2. Return name, email, phone, and relevant text from resume_text

Guidelines:
- ALWAYS use LIKE '%keyword%' for searching in resume_text and cover_letter_text
- Search is case-INSENSITIVE, so use LIKE operator
- For skills: WHERE resume_text LIKE '%Java%' OR cover_letter_text LIKE '%Java%'
- For location: WHERE resume_text LIKE '%Delhi%' OR cover_letter_text LIKE '%Delhi%'
- For experience: Look for patterns like "5 years", "8 years" in resume_text
- ALWAYS use OR between resume_text and cover_letter_text for broader matches
- Use LIMIT 10 for top results

IMPORTANT EXAMPLES:
- "Java developers" → SELECT name, email FROM candidates WHERE resume_text LIKE '%Java%' OR cover_letter_text LIKE '%Java%' LIMIT 10;
- "Senior Java in Delhi" → SELECT name, email FROM candidates WHERE (resume_text LIKE '%Java%' OR cover_letter_text LIKE '%Java%') AND (resume_text LIKE '%Delhi%' OR cover_letter_text LIKE '%Delhi%') LIMIT 10;

Output format:
SQL_QUERY: <your sql query here>

Be concise. Focus on generating working SQL."""
    
    def generate_sql_from_natural_language(self, user_query: str) -> Dict[str, Any]:
        """
        Use LLM to convert natural language to SQL
        Implements automatic fallback between OpenAI and Gemini
        """
        try:
            content = self.llm_manager.generate_completion(
                self.get_system_prompt(),
                user_query
            )
            
            # Parse the response
            if "SQL_QUERY:" in content:
                sql_match = re.search(r'SQL_QUERY:\s*(.+?)(?:\n|$)', content, re.DOTALL)
                if sql_match:
                    sql_query = sql_match.group(1).strip()
                    # Clean up the SQL query
                    sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
                    
                    return {
                        "type": "sql_query",
                        "query": sql_query,
                        "raw_response": content,
                        "provider": self.llm_manager.get_current_provider()
                    }
            
            if "UNKNOWN_QUERY:" in content:
                explanation = content.split("UNKNOWN_QUERY:")[1].strip()
                return {
                    "type": "unknown_query",
                    "explanation": explanation,
                    "raw_response": content,
                    "provider": self.llm_manager.get_current_provider()
                }
            
            # Fallback: try to extract SQL directly
            sql_match = re.search(r'SELECT\s+.*?;', content, re.IGNORECASE | re.DOTALL)
            if sql_match:
                return {
                    "type": "sql_query",
                    "query": sql_match.group(0).strip(),
                    "raw_response": content,
                    "provider": self.llm_manager.get_current_provider()
                }
            
            return {
                "type": "unknown_query",
                "explanation": "Could not generate a valid SQL query",
                "raw_response": content,
                "provider": self.llm_manager.get_current_provider()
            }
            
        except Exception as e:
            return {
                "type": "error",
                "error": str(e)
            }
    
    def query_database(self, sql_query: str) -> QueryResult:
        """
        Tool: Execute a SQL query against the database
        Includes validation and safety checks
        """
        # Validate the SQL query
        is_valid, error_msg = self.validator.is_safe_query(sql_query)
        
        if not is_valid:
            return QueryResult(
                success=False,
                error=f"Query validation failed: {error_msg}",
                sql_query=sql_query
            )
        
        # Execute the query
        return self.db_manager.execute_query(sql_query)
    
    def record_unknown_query(self, query: str, explanation: str) -> Dict[str, str]:
        """
        Tool: Log queries that couldn't be processed
        """
        log_entry = {
            "query": query,
            "explanation": explanation,
            "timestamp": os.popen('date').read().strip()
        }
        
        # In production, this would write to a log file or database
        print(f"[UNKNOWN QUERY LOGGED] {json.dumps(log_entry, indent=2)}")
        
        return {
            "status": "logged",
            "message": f"I couldn't process that query. {explanation}"
        }
    
    def process_query(self, user_query: str) -> Dict[str, Any]:
        """
        Main reasoning loop: process a user query end-to-end
        """
        # Step 1: Generate SQL from natural language (with auto-fallback)
        generation_result = self.generate_sql_from_natural_language(user_query)
        
        # Step 2: Handle different result types
        if generation_result["type"] == "sql_query":
            sql_query = generation_result["query"]
            
            # Step 3: Execute the query
            query_result = self.query_database(sql_query)
            
            return {
                "success": query_result.success,
                "sql_query": sql_query,
                "data": query_result.data,
                "error": query_result.error,
                "type": "query_result",
                "provider": generation_result.get("provider", "unknown")
            }
        
        elif generation_result["type"] == "unknown_query":
            explanation = generation_result["explanation"]
            self.record_unknown_query(user_query, explanation)
            
            return {
                "success": False,
                "message": explanation,
                "type": "unknown_query",
                "provider": generation_result.get("provider", "unknown")
            }
        
        else:  # error
            return {
                "success": False,
                "error": generation_result.get("error", "Unknown error occurred"),
                "type": "error"
            }


# Initialize the global agent instance
recruiting_agent = None

def get_agent():
    """Get or create the recruiting agent instance"""
    global recruiting_agent
    if recruiting_agent is None:
        recruiting_agent = RecruitingAgent()
    return recruiting_agent


if __name__ == "__main__":
    # Test the agent
    agent = get_agent()
    
    test_queries = [
        "Show me candidates with AWS experience",
        "Find candidates with more than 5 years of experience in Java",
        "List all candidates from Delhi",
        "Who knows Spring Boot?"
    ]
    
    print("=== Testing Recruiting Agent ===\n")
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        print("-" * 50)
        
        result = agent.process_query(query)
        
        if result["success"]:
            print(f"Provider: {result.get('provider', 'unknown')}")
            print(f"SQL Generated: {result['sql_query']}")
            print(f"\nResults ({len(result['data'])} found):")
            for row in result['data']:
                print(f"  - {row.get('name', 'N/A')}: {row.get('email', 'N/A')}")
        else:
            print(f"Error: {result.get('error') or result.get('message', 'Unknown error')}")
        
        print()