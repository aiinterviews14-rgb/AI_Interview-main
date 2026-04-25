import os
import re
import json
import time
import threading
import datetime
import PyPDF2
import random
from groq import Groq
import fitz
import cv2
import numpy as np
import base64
# Report Generation Imports
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xml.sax.saxutils import escape as xml_escape
import resume_analyzer # Import for ATS recommendations
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT

class InterviewManager:

    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY")
        self.lock = threading.Lock() # For thread-safe operations during report generation
        # Check if the key is missing or is the default placeholder
        if not self.api_key or "your_groq_api_key_here" in self.api_key:
            print("[WARN] Warning: GROQ_API_KEY is missing or invalid. Running in Offline/Demo Mode.")
            self.client = None
        else:
            try:
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                print(f"Error initializing Groq client: {e}")
                self.client = None
        self.model_name = "llama-3.1-8b-instant"
        self.candidate_name = ""
        self.resume_text = ""
        self.projects_mentioned = []
        self.skills_mentioned = []
        self.technologies_mentioned = []
        self.core_subjects = []
        self.history = []
        self.evaluations = []
        self.submitted_solutions = []
        self.violations = [] # Track security violations
        self.proctor_score = 100 # New: Integrity/Proctoring Score
        self.start_time = datetime.datetime.now() # Approximate start
        self.session_id = str(int(time.time())) # Unique session for evidence isolation
        self.credit_consumed = False # Track if billing occurred for this session
        self.resume_path = None # Path to original resume PDF for auto-deletion
        self.resume_score = None # New: ATS Score from analysis
        self.resume_analysis_results = None # Full results from ATS engine
        self.module_topic = None # New: Specialized Assessment Module Topic (e.g. System Design)
        self.evidence_images = []  # Pre-decoded (path, label) tuples for past report generation
        self.candidate_photo = None # Base64 extracted photo from resume
        self.profile_face_hist = None # NEW: Pre-computed face histogram for lightweight identity verification
        self.icebreaker_stage = 'start'
        self.icebreaker_count = 0
        self.max_icebreakers = 2
        self.asked_topics = []
        # Two coding problems per session, sampled once from problems JSON pool
        self.session_coding_problems = []
        # STRICT INTERVIEW FLOW (Requested)
        self.plan_id = 0
        self.current_step = 0
        self.interview_flow = self._get_default_flow()

    def reset(self): 
        print("🔥 RESET FUNCTION CALLED")

        with self.lock:
            self.history = []
            self.evaluations = []
            self.submitted_solutions = []
            self.violations = []
            self.proctor_score = 100

            self.start_time = datetime.datetime.now()
            self.session_id = str(int(time.time()))

            self.projects_mentioned = []
            self.skills_mentioned = []
            self.technologies_mentioned = []
            self.core_subjects = []

            self.resume_score = None
            self.resume_analysis_results = None

            self.evidence_images = []
            self.candidate_photo = None

            self.icebreaker_stage = 'start'
            self.icebreaker_count = 0
            self.asked_topics = []

            self.current_step = 0
            self.credit_consumed = False
            self.profile_face_hist = None

            if hasattr(self, 'evidence_path'):
                self.evidence_path = None

            self.session_coding_problems = []

        return True

    def _refresh_session_coding_problems(self):
        """Pick 2 distinct random problems from code_engine JSON for this session."""
        pool = []
        try:
            from code_engine.problem_loader import load_problems
            pool = load_problems() or []
        except Exception as e:
            print(f"[WARN] Coding pool load failed: {e}")
        with self.lock:
            if not pool:
                self.session_coding_problems = []
                return
            k = min(2, len(pool))
            self.session_coding_problems = random.sample(pool, k)
            ids = [p.get("id") for p in self.session_coding_problems]
            print(f"[CODING] Session problems (2 random): ids={ids}")

    def _get_default_flow(self, plan_id=0):
        """Standard full flow: basics → resume (skills & projects from CV) → scenarios → tech → case → behavioral → 2 coding → HR → leadership wrap-up"""
        return [
            "greeting",
            "warmup",
            "warmup",
            "intro",
            "resume_skills",
            "resume_projects",
            "resume_overview",
            "scenario_technical",
            "technical_core",
            "technical_advanced",
            "case_study",
            "scenario_behavioral",
            "code",
            "code",
            "scenario_hr",
            "leadership",
            "teamwork",
            "adaptability",
            "future_goals",
            "conclusion"
        ]

    def set_module_topic(self, topic):
        """Sets a specialized assessment topic (e.g. System Design, Technical Core)."""
        self.module_topic = topic
        if topic:
            print(f" ð¯ [MANAGER] Session Module set to: {topic}")

    def update_flow_for_plan(self, plan_id, practice_section=None):
        """Adjusts depth and length of interview based on plan ID or Practice Mode"""
        self.plan_id = int(plan_id)
        self.practice_mode = practice_section is not None
        self.practice_section = practice_section
        self.current_step = 0 # Restart always when plan context changes
        # 1. HANDLE PRACTICE MODE (Focused Sections)
        if self.practice_mode:
            if practice_section == 'intro':
                self.interview_flow = ["greeting", "warmup", "intro", "conclusion"]
            elif practice_section == 'projects':
                self.interview_flow = ["greeting", "resume_skills", "resume_projects", "conclusion"]
            elif practice_section == 'technical':
                self.interview_flow = [
                    "greeting", "resume_skills", "resume_projects", "resume_overview",
                    "scenario_technical", "technical_core", "technical_advanced",
                    "case_study", "scenario_behavioral", "code", "code", "scenario_hr", "conclusion"
                ]
            elif practice_section == 'case_study':
                self.interview_flow = ["greeting", "case_study", "case_study", "conclusion"]
            elif practice_section == 'behavioral' or practice_section == 'hr':
                self.interview_flow = ["greeting", "scenario_behavioral", "scenario_hr", "teamwork", "conclusion"]
            else:
                self.interview_flow = ["greeting", "warmup", "conclusion"]
            print(f"ð¯ [FLOW] Practice Mode Activated: {practice_section}")
        # 2. HANDLE STANDARD PLAN FLOW
        elif self.plan_id == 1:
            # Starter: basics → resume skills/projects from CV → behavioral → coding → HR → close
            self.interview_flow = [
                "greeting",
                "warmup",
                "resume_skills",
                "resume_projects",
                "resume_overview",
                "scenario_technical",
                "technical_core",
                "scenario_behavioral",
                "code",
                "scenario_hr",
                "conclusion"
            ]
            print(f"ð [FLOW] Reduced Interview Flow for Starter Plan (Plan 1)")
        elif self.plan_id == 2:
            # ATS Pro: basics → resume (skills, projects, overview from CV) → rest; HR after coding
            self.interview_flow = [
                "greeting", "warmup", "warmup", "intro",
                "resume_skills", "resume_projects", "resume_overview",
                "scenario_technical", "technical_core", "technical_advanced",
                "case_study", "scenario_behavioral",
                "code", "code", "scenario_hr", "conclusion"
            ]
            print(f"ð [FLOW] Standard Flow for ATS Pro Plan (Plan 2)")
        elif self.plan_id == 3:
            # Proctor Elite: basics → resume from CV → …; HR after coding
            self.interview_flow = [
                "greeting", "warmup", "warmup", "intro",
                "resume_skills", "resume_projects", "resume_overview",
                "scenario_technical", "technical_core", "technical_advanced",
                "case_study", "scenario_behavioral",
                "code", "code",
                "scenario_hr", "leadership", "teamwork", "adaptability", "conclusion"
            ]
            print(f"ð¡ï¸ [FLOW] Full Flow for Proctor Elite Plan (Plan 3)")
        elif self.plan_id == 4:
            # Ultimate Bundle (Plan 4): The exhaustive "Elite Ultra" flow
            self.interview_flow = self._get_default_flow()
            print(f"ð [FLOW] Full Elite Flow Activated (Plan {self.plan_id})")
        else:
            # Default/Free/Unknown: exactly 5 scored questions; next step resolves to conclusion on the backend
            self.interview_flow = [
                "greeting",
                "warmup",
                "resume_skills",
                "resume_projects",
                "technical_core",
            ]
            print(f"ð [FLOW] Demo Flow (5 questions) Activated (Plan {self.plan_id})")
        with self.lock:
            self.history = []
            self.evaluations = []
            self.submitted_solutions = []
            self.violations = []
            self.proctor_score = 100
            self.evidence_path = None
            self.start_time = datetime.datetime.now()
            self.asked_topics = []
            self.icebreaker_count = 0
            self.icebreaker_stage = 'start'
            self.current_step = 0 # Reset flow step
            self.session_id = str(int(time.time())) # New session ID on reset
            print("ð Interview State Reset Successfully")
        # Fresh random coding pair for this flow (200-problem pool)
        self._refresh_session_coding_problems()

    def get_next_category(self):
        """STRICT FLOW CONTROLLER: Decides next stage and increments step"""
        with self.lock:
            if self.current_step >= len(self.interview_flow):
                return "conclusion"
            category = self.interview_flow[self.current_step]
            self.current_step += 1
            return category

    def generate_icebreaker_response(self, user_reply):
        """Generate a polite, brief acknowledgement to user's small talk"""
        if not self.client: return "That's good to hear. Let's proceed."
        try:
            prompt = f"""
            You are a professional, friendly AI interviewer. The candidate just replied to your small talk question.
            Candidate's Reply: "{user_reply}"
            Generate a brief, warm, natural response (1 sentence only).
            Example: "That sounds great, I'm glad to hear it." or "I understand, these interviews can be nervous."
            Do not ask another question yet. Just acknowledge.
            """
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=30,
                timeout=10.0
            )
            return response.choices[0].message.content.strip()
        except:
            return "That's good. Moving on."
    def load_resume(self, file_path):
        """Extracts text and metadata from PDF resume."""
        if not os.path.exists(file_path):
            return False, "File not found"
        
        text = ""
        try:
            # 1. Text Extraction with fitz (PyMuPDF)
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            
            # 2. Extract Candidate Photo
            for page_index in range(len(doc)):
                page = doc[page_index]
                image_list = page.get_images(full=True)
                if image_list:
                    xref = image_list[0][0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    self.candidate_photo = base64.b64encode(image_bytes).decode('utf-8')
                    break
            doc.close()
            
            self.resume_text = text
            self.resume_path = file_path
            self._extract_entities(text)
            return True, "Resume loaded successfully"
        except Exception as e:
            print(f"Error loading resume: {e}")
            return False, str(e)

    def _extract_entities(self, text):
        """Parses resume text for skills, tools, projects, and subjects (used for resume-grounded questions)."""
        if not self.client: return
        prompt = (
            f"From this resume text, extract ONLY items the candidate explicitly wrote. Return JSON with arrays of short strings: "
            f"{{\"skills\":[], \"technologies\":[], \"projects\":[], \"subjects\":[]}}. "
            f"skills = languages/frameworks/libraries (e.g. Python, React). technologies = tools/platforms (e.g. AWS, Docker, Git). "
            f"projects = project or product names / thesis titles. subjects = courses or domains (e.g. OS, ML). Text:\n{text[:4000]}"
        )
        try:
            response = self.client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}], temperature=0.1)
            data = json.loads(re.search(r"\{.*\}", response.choices[0].message.content, re.DOTALL).group())
            self.skills_mentioned = data.get('skills', [])
            self.technologies_mentioned = data.get('technologies', []) or data.get('tools', [])
            self.projects_mentioned = data.get('projects', [])
            self.core_subjects = data.get('subjects', [])
        except: pass

    def verify_candidate_match(self, name, resume_text):
        """Checks if registration name matches resume content."""
        if not name or not resume_text: return False, "Missing info"
        if name.lower() in resume_text.lower(): return True, name
        if not self.client: return False, "Unknown"
        prompt = f"Does '{name}' match any name in this resume? Snippet: {resume_text[:400]}. Return 'YES: [Name]' or 'NO'."
        try:
            res = self.client.chat.completions.create(model=self.model_name, messages=[{"role": "user", "content": prompt}]).choices[0].message.content
            if 'YES' in res.upper():
                return True, res.split(':')[-1].strip() if ':' in res else name
            return False, "Mismatch"
        except: return False, "Error"

    def analyze_resume(self):
        """Runs background ATS analysis."""
        if not self.resume_text: return
        try:
            results = resume_analyzer.analyze_resume_ats(self.resume_text, self.skills_mentioned)
            self.resume_analysis_results = results
            self.resume_score = results.get('score', 0)
        except Exception as e:
            print(f"Error in analyze_resume: {e}")

    def calculate_score(self):
        """Calculates final score by averaging evaluations and coding results."""
        total_score = 0
        points_count = 0
        # 1. Answer Evaluations (each worth up to 10 points)
        if self.evaluations:
            with self.lock:
                for e in self.evaluations:
                    s = self.sf(e.get('score', 0))
                    total_score += s
                    points_count += 1
        # 2. Coding Submissions (each worth up to 10 points)
        if self.submitted_solutions:
            for s in self.submitted_solutions:
                # If not already analyzed, analyze now
                if 'analysis' not in s:
                    try:
                        res = self.analyze_coding_submission(s)
                        s['analysis'] = res
                        # Extract a single score (Correctness is usually 1-10)
                        s['score'] = res.get('breakdown', {}).get('Correctness', 5)
                        # Carry over test case info if provided by frontend
                        s['test_cases_passed'] = res.get('test_cases_passed', s.get('test_cases_passed', 0))
                        s['total_test_cases'] = res.get('total_test_cases', s.get('total_test_cases', 0))
                    except:
                        s['score'] = 5 # Fallback
                total_score += self.sf(s.get('score', 0))
                points_count += 1
        if points_count == 0: return 0
        # Final Score as Percentage (total / (max_possible_10_per_item)) * 100
        percentage = (total_score / (points_count * 10)) * 100
        return int(percentage)

    def sf(self, v):
        """Safe Float converter - handles None and strings with numbers"""
        try:
            if v is None: return 0.0
            if isinstance(v, str):
                m = re.search(r'(\d+(\.\d+)?)', v)
                return float(m.group(1)) if m else 0.0
            return float(v)
        except: return 0.0

    def eval_response_quality(self, e):
        """Per-question 0–10 signal for factual correctness; falls back to overall score when needed."""
        return self.sf(
            e.get(
                "correctness_score",
                e.get("correctness", e.get("accuracy", e.get("score", 0))),
            )
        )

    def get_hiring_response_metrics(self, evals=None):
        """
        Verbal/coding factual accuracy used for pass vs not-recommended hiring labels.
        If evals is provided (e.g. snapshot under lock), use it; otherwise copy self.evaluations.
        """
        if evals is None:
            with self.lock:
                evals = list(self.evaluations)
        avg_corr = (
            sum(self.eval_response_quality(e) for e in evals) / float(len(evals)) if evals else 0.0
        )
        coding_total = len(self.submitted_solutions)
        coding_passed = 0
        coding_avg = 0.0
        if coding_total:
            cvals = []
            for s in self.submitted_solutions:
                tt = self.sj(s.get("total_test_cases", 0))
                tp = self.sj(s.get("test_cases_passed", 0))
                if tt > 0:
                    cvals.append((tp / float(tt)) * 10.0)
                    if tp >= tt:
                        coding_passed += 1
                else:
                    cvals.append(self.sf(s.get("score", 0)))
            coding_avg = sum(cvals) / len(cvals) if cvals else 0.0
        pass_avg, pass_floor = 6.0, 4.0
        verbal_ok = (not evals) or (
            avg_corr >= pass_avg and all(self.eval_response_quality(e) >= pass_floor for e in evals)
        )
        coding_ok = (coding_total == 0) or (coding_avg >= pass_avg)
        responses_adequate = verbal_ok and coding_ok
        return {
            "avg_corr": avg_corr,
            "coding_avg": coding_avg,
            "coding_total": coding_total,
            "coding_passed": coding_passed,
            "verbal_ok": verbal_ok,
            "coding_ok": coding_ok,
            "responses_adequate": responses_adequate,
        }

    def sj(self, v):
        """Safe Jump/Int converter - handles None"""
        try:
            if v is None: return 0
            if isinstance(v, str):
                m = re.search(r'\d+', v)
                return int(m.group()) if m else 0
            return int(v)
        except: return 0

    def create_performance_chart(self, filename="performance_chart.png"):
        """Create performance visualization chart"""
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
        fig = Figure(figsize=(8, 4))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        categories = []
        scores = []
        with self.lock:
            for eval_item in self.evaluations:
                q_type = eval_item.get('type', 'General')
                score = self.sf(eval_item.get('score', 0))
                categories.append(q_type)
                scores.append(score)
        if not scores: return None
        # Aggregate by category
        from collections import defaultdict
        cat_scores = defaultdict(list)
        for cat, score in zip(categories, scores):
            cat_scores[cat].append(score)
        cat_names = list(cat_scores.keys())
        cat_avgs = [sum(v)/len(v) for v in cat_scores.values()]
        colors_list = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c']
        ax.barh(cat_names, cat_avgs, color=colors_list[:len(cat_names)])
        ax.set_xlabel('Average Score', fontsize=11, fontweight='bold')
        ax.set_title('Performance by Category', fontsize=13, fontweight='bold')
        ax.set_xlim(0, 10)
        ax.grid(axis='x', alpha=0.3)
        for i, v in enumerate(cat_avgs):
            ax.text(v + 0.2, i, f'{v:.1f}', va='center', fontweight='bold')
        fig.tight_layout()
        fig.savefig(filename, dpi=300, bbox_inches='tight')
        return filename

    def create_coding_chart(self, filename="coding_performance_chart.png"):
        """Create coding performance chart"""
        if not self.submitted_solutions: return None
        titles = [s.get('title', f"Prob {i+1}") for i, s in enumerate(self.submitted_solutions)]
        norm_scores = []
        for s in self.submitted_solutions:
             # Use AI score if test cases strictly not run, else use test cases
             passed = self.sj(s.get('test_cases_passed', 0))
             total = self.sj(s.get('total_test_cases', 0))
             if total > 0:
                 score = (passed / total) * 10
             else:
                 # Fallback to AI Correctness score if available
                 analysis = s.get('analysis', {})
                 score = analysis.get('breakdown', {}).get('Correctness', s.get('score', 5))
             norm_scores.append(self.sf(score))
        if not norm_scores: return None
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
        fig = Figure(figsize=(6, 4))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        colors = ['#2ecc71' if s >= 7 else '#e74c3c' for s in norm_scores]
        ax.bar(titles, norm_scores, color=colors, width=0.5)
        ax.set_ylabel('Score (out of 10)')
        ax.set_title('Coding Problem Scores')
        ax.set_ylim(0, 10)
        fig.autofmt_xdate(rotation=45)
        fig.tight_layout()
        fig.savefig(filename, dpi=300)
        return filename

    def create_coding_skills_chart(self, filename="coding_skills_chart.png"):
        """Create coding skills breakdown chart based on actual metrics"""
        if not self.submitted_solutions: return None
        # Aggregating metrics across all solutions
        metrics = {
            "Code Quality": [],
            "Edge Cases": [],
            "Space Complexity": [],
            "Time Complexity": [],
            "Algorithm": [],
            "Correctness": []
        }
        for s in self.submitted_solutions:
            analysis = s.get('analysis', {})
            breakdown = analysis.get('breakdown', {})
            for key in metrics.keys():
                val = breakdown.get(key)
                if val is not None:
                    metrics[key].append(self.sf(val))
        # Calculate averages for each metric
        final_metrics = {}
        for k, v in metrics.items():
            if v:
                final_metrics[k] = sum(v) / len(v)
            else:
                # If no analysis, fallback to test case score
                passed = sum(self.sj(s.get('test_cases_passed', 0)) for s in self.submitted_solutions)
                total = sum(self.sj(s.get('total_test_cases', 0)) for s in self.submitted_solutions)
                final_metrics[k] = (passed / total * 10) if total > 0 else 5
        names = list(final_metrics.keys())
        values = [max(0, m) for m in final_metrics.values()]
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
        fig = Figure(figsize=(6, 4))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        y_pos = range(len(names))
        ax.barh(y_pos, values, align='center', color='#3498db')
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.invert_yaxis()  # labels read top-to-bottom
        ax.set_xlabel('Score')
        ax.set_title('Coding Skills Breakdown')
        ax.set_xlim(0, 10)
        ax.grid(axis='x', linestyle='--', alpha=0.7)
        for i, v in enumerate(values):
            ax.text(v + 0.1, i, f'{v:.1f}', va='center', fontweight='bold', fontsize=9)
        fig.tight_layout()
        fig.savefig(filename, dpi=300)
        return filename

    def create_cfk_chart(self, filename="cfk_chart.png"):
        """Create Confidence, Accuracy, Communication Skills chart"""
        if not self.evaluations: return None
        # Calculate averages
        total = len(self.evaluations)
        if total == 0: return None
        def safe_float(val, default=0.0):
            try:
                if val is None: return default
                return float(val)
            except (ValueError, TypeError):
                return default
        with self.lock:
            avg_conf = sum(safe_float(e.get('confidence', 0)) for e in self.evaluations) / total
            # Accuracy: Use technical_accuracy if available, else overall_score/score
            acc_sum = 0
            for e in self.evaluations:
                val = e.get('technical_accuracy')
                if val is None: val = e.get('score', e.get('overall_score', 0))
                acc_sum += safe_float(val)
            avg_acc = acc_sum / total
            # Communication
            avg_comm = sum(safe_float(e.get('communication_clarity', e.get('fluency', 0))) for e in self.evaluations) / total
        labels = ['Confidence', 'Accuracy', 'Comm Skills']
        values = [avg_conf, avg_acc, avg_comm]
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
        fig = Figure(figsize=(6, 4))
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        colors_list = ['#f1c40f', '#e67e22', '#3498db']
        bars = ax.bar(labels, values, color=colors_list)
        ax.set_ylim(0, 10)
        ax.set_ylabel('Score (0-10)')
        ax.set_title('Performance Metrics')
        for bar in bars:
            yval = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, f'{yval:.1f}', ha='center', fontweight='bold')
        fig.tight_layout()
        fig.savefig(filename, dpi=300)
        return filename

    def create_overall_pie_chart(self, filename="overall_pie_chart.png"):
        """Create a pie chart showing Score Distribution by Topic"""
        if not self.evaluations and not self.submitted_solutions: return None
        # Aggregate scores by Topic
        topic_scores = {}
        total_possible = 0
        # 1. Theory Topics
        with self.lock:
            for e in self.evaluations:
                topic = e.get('type', 'General').replace('_', ' ').title()
                s = e.get('score', e.get('overall_score', 0))
                if s is None: s = 0
                if isinstance(s, str):
                    try:
                        match = re.search(r'(\d+(?:\.\d+)?)', s)
                        s = float(match.group(1)) if match else 0
                    except: s = 0
                topic_scores[topic] = topic_scores.get(topic, 0) + float(s)
                total_possible += 10
        # 2. Coding Topic
        if self.submitted_solutions:
             coding_total = 0
             for s in self.submitted_solutions:
                 passed = s.get('test_cases_passed', 0)
                 total = s.get('total_test_cases', 1) or 1
                 coding_total += (passed / total) * 10
                 total_possible += 10
             if coding_total > 0:
                topic_scores['Coding'] = topic_scores.get('Coding', 0) + coding_total
        if not topic_scores or total_possible == 0: return None
        # Prepare Data for Pie Chart (Grouped by major Category)
        # Mapping to consolidate 20+ sub-tags into 5 readable domains
        category_map = {
            'Technical': ['Technical', 'Technical Core', 'Technical Advanced', 'Technical Hr', 'Scenario Technical'],
            'Behavioral': ['Behavioral', 'Hr/Behavioral', 'Teamwork', 'Leadership', 'Adaptability', 'Future Goals', 'Scenario Hr', 'Scenario Behavioral'],
            'Resume & Projects': ['Resume Overview', 'Resume Skills', 'Resume Projects', 'Project', 'Internship'],
            'Coding': ['Coding'],
            'Intro/Basics': ['Intro', 'Warmup', 'Conclusion', 'Case Study']
        }
        grouped_scores = {}
        for category, sub_tags in category_map.items():
            s = 0
            for tag in sub_tags:
                tag_title = tag.title()
                if tag_title in topic_scores:
                    s += topic_scores.pop(tag_title)
            if s > 0:
                grouped_scores[category] = s
        # Any remaining topics not in map
        for topic, score in topic_scores.items():
            grouped_scores[topic] = grouped_scores.get(topic, 0) + score
        labels = list(grouped_scores.keys())
        sizes = list(grouped_scores.values())
        # Use a professional, consistent color palette
        colors_list = ['#3498db', '#2ecc71', '#9b59b6', '#f1c40f', '#e67e22', '#1abc9c', '#e74c3c']
        # Calculate overall gap
        remaining = total_possible - sum(sizes)
        if remaining > 0:
            labels.append('Gap')
            sizes.append(remaining)
            colors_list = colors_list[:len(labels)-1] + ['#ecf0f1'] # Light gray for gap
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
        fig = Figure(figsize=(8, 6)) # Larger canvas for legend
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        # Create Donut Chart (wedgeprops width creates the hole)
        wedges, texts, autotexts = ax.pie(
            sizes,
            autopct='%1.1f%%',
            startangle=140,
            colors=colors_list,
            pctdistance=0.75,
            wedgeprops=dict(width=0.4, edgecolor='w', linewidth=2)
        )
        # Clean up autotexts
        for i, a in enumerate(autotexts):
            if sizes[i] < (total_possible * 0.05): # Hide labels for tiny slivers
                a.set_text("")
            else:
                a.set_color('#1E3A5F')
                a.set_weight('bold')
                a.set_size(9)
        # Add Professional Legend at the side
        ax.legend(wedges, labels, title="Score Categories", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
        ax.set_title("Overall Score Percentage", pad=20, fontsize=14, weight='bold')
        fig.tight_layout()
        fig.subplots_adjust(right=0.75) # Make room for legend
        fig.savefig(filename, dpi=300, bbox_inches='tight')
        return filename

    def generate_final_recommendation(self, evals_snapshot=None):
        """Generate a structured final recommendation using LLM.
        evals_snapshot: optional list copied under lock so the prompt matches the PDF snapshot."""
        if not self.client:
            return {
                "summary": "Review pending (Offline Mode).",
                "improvements": ["Ensure API key is set."],
                "next_steps": ["Check configuration."]
            }
        security_status_text = "Clean"
        if len(self.violations) >= 3:
            security_status_text = "TERMINATED due to multiple security violations"
        elif self.violations:
            security_status_text = "Warnings Issued"
        ev_for_prompt = evals_snapshot if evals_snapshot is not None else list(self.evaluations)
        hrm = self.get_hiring_response_metrics(ev_for_prompt)
        gate = hrm["responses_adequate"]
        summary_prompt = f"""
        You are an expert AI Technical Interviewer creating a final report for candidate "{self.candidate_name}".
        Analyze the following interview performance data and generate a structured recommendation.
        Interview Data:
        - Overall Score: {self.calculate_score()}/100
        - Questions Answered: {len(ev_for_prompt)}
        - Coding Problems Solved: {len(self.submitted_solutions)}
        - Security Status: {security_status_text}
        - Verbal answer accuracy average (0-10, correctness/accuracy or overall score fallback): {hrm['avg_corr']:.1f}
        - Coding performance average (0-10): {hrm['coding_avg']:.1f}
        - Official response-accuracy pass gate (verbal avg >= 6/10 with no item below 4/10; coding avg >= 6/10 when coding exists): {"PASS" if gate else "FAIL"}
        Rules for the summary hiring stance:
        - If Security Status indicates termination or critical integrity failure, state NOT recommended for hire.
        - If the pass gate is FAIL, you MUST state NOT recommended for hire and cite weak factual or coding accuracy — do not recommend based on fluency or charisma alone.
        - If the pass gate is PASS, align tone with the overall score (further review vs strong recommendation).
        Evaluations:
        {json.dumps([{'q': e.get('question'), 'score': e.get('score'), 'correctness': e.get('correctness_score', e.get('correctness')), 'verbatim_len': len((e.get('verbatim_transcript') or e.get('answer') or '')), 'type': e.get('type')} for e in ev_for_prompt], indent=2)}
        Return a VALID JSON object with exactly these keys:
        {{
            "summary": "A balanced 100-word executive summary of performance and hiring recommendation.",
            "improvements": ["List of 3-4 specific areas where the candidate needs improvement (technical or soft skills)."],
            "next_steps": ["List of 3-4 actionable next steps or learning resources for the candidate to grow."]
        }}
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            print(f"LLM Error: {e}")
            return {
                "summary": "Candidate assessment complete. Performance data is available in the detailed report.",
                "improvements": ["Review technical concepts.", "Practice coding problems."],
                "next_steps": ["Focus on weak areas identified in the charts."]
            }

    def generate_pdf_report(self, filename, plan_id=0):
        """Official structured assessment PDF (aligned with standard interview report layout)."""
        from collections import defaultdict
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph as RLParagraph,
            Spacer,
            Table,
            TableStyle,
            Image,
            HRFlowable,
            KeepTogether,
            CondPageBreak,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        import datetime
        import tempfile

        margin = 0.55 * inch
        C_MAIN = colors.HexColor('#0f172a')
        C_ACCENT = colors.HexColor('#1d4ed8')
        C_SUCCESS = colors.HexColor('#047857')
        C_DANGER = colors.HexColor('#b91c1c')
        C_MUTED = colors.HexColor('#64748b')
        C_BG = colors.HexColor('#f8fafc')
        C_BORDER = colors.HexColor('#cbd5e1')
        C_WHITE = colors.white

        def _on_page(canvas, doc_):
            canvas.saveState()
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(C_MUTED)
            canvas.drawRightString(A4[0] - margin, 0.42 * inch, f"-- {canvas.getPageNumber()} --")
            canvas.restoreState()

        doc = SimpleDocTemplate(
            filename, pagesize=A4,
            topMargin=margin, bottomMargin=0.55 * inch, leftMargin=margin, rightMargin=margin,
            onFirstPage=_on_page, onLaterPage=_on_page,
        )
        story = []
        _chart_tmp = []
        gap_sm = Spacer(1, 0.06 * inch)
        gap_md = Spacer(1, 0.09 * inch)

        def safe_para(text, style, allow_xml=False):
            if not text:
                return RLParagraph("", style)
            if allow_xml:
                return RLParagraph(str(text), style)
            clean_text = str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return RLParagraph(clean_text, style)

        def _band(avg):
            if avg is None or avg <= 0:
                return "NOT ATTEMPTED"
            if avg < 3:
                return "CRITICAL"
            if avg < 5:
                return "NEEDS IMPROVEMENT"
            if avg < 6.5:
                return "AVERAGE"
            if avg < 8:
                return "GOOD"
            return "STRONG"

        s_conf = ParagraphStyle('Conf', fontSize=9, textColor=C_DANGER, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=4)
        s_main_title = ParagraphStyle('MainT', fontSize=16, textColor=C_MAIN, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=6)
        s_sub = ParagraphStyle('Sub2', fontSize=9, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=8)
        s_title = ParagraphStyle('Title', fontSize=14, textColor=C_MAIN, fontName='Helvetica-Bold', spaceAfter=6)
        s_head = ParagraphStyle('Head', fontSize=11, textColor=C_MAIN, fontName='Helvetica-Bold', spaceBefore=10, spaceAfter=4, leading=13)
        s_chart_cap = ParagraphStyle('ChCap', fontSize=8, textColor=C_MUTED, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceBefore=2, spaceAfter=3)
        s_norm = ParagraphStyle('Norm', fontSize=9, leading=12, textColor=colors.HexColor('#334155'), fontName='Helvetica')
        s_bold = ParagraphStyle('Bold', fontSize=9, leading=12, textColor=C_MAIN, fontName='Helvetica-Bold')
        s_small = ParagraphStyle('Small', fontSize=8, leading=11, textColor=C_MUTED, fontName='Helvetica')
        s_badge = ParagraphStyle('Badge', fontSize=9, fontName='Helvetica-Bold', textColor=C_WHITE, alignment=TA_CENTER)

        with self.lock:
            evals_copy = list(self.evaluations)
            viol_report = list(self.violations)

        ai_data = self.generate_final_recommendation(evals_copy)
        ai_summary = ai_data.get('summary', 'Evaluation complete.')
        improvements = ai_data.get('improvements') or []
        next_steps = ai_data.get('next_steps') or []

        def _violations_unusual(vlist):
            """Omit only routine low-severity monitoring snapshots; keep all other integrity / proctor events."""
            out = []
            for v in vlist or []:
                t = str(v.get("type") or "").lower()
                sev = str(v.get("severity") or "MEDIUM").upper()
                if t == "snapshot" and sev == "LOW":
                    continue
                out.append(v)
            return out

        unusual_list = _violations_unusual(viol_report)
        unusual_ct = len(unusual_list)

        ov_score = (self.calculate_score() / 10.0) if hasattr(self, 'calculate_score') else 0
        pct_score = int(round(ov_score * 10))
        is_sec_fail = any(v.get('severity') == 'CRITICAL' for v in self.violations) or (hasattr(self, 'proctor_score') and self.proctor_score == 0)

        t_q = len(evals_copy) or 1
        hrm = self.get_hiring_response_metrics(evals_copy)
        avg_corr = hrm["avg_corr"]
        coding_total = hrm["coding_total"]
        coding_passed = hrm["coding_passed"]
        coding_avg = hrm["coding_avg"]
        responses_adequate = hrm["responses_adequate"]
        avg_fluency = sum(self.sf(e.get('fluency', 0)) for e in evals_copy) / t_q if evals_copy else 0
        proctor_pct = float(getattr(self, 'proctor_score', 100) or 100)

        status_text, status_color = ("QUALIFIED / RECOMMENDED", C_SUCCESS)
        hire_line = "HIRING DECISION: RECOMMENDED FOR FURTHER REVIEW"
        if is_sec_fail:
            status_text, status_color = ("SECURITY REJECTED", C_DANGER)
            hire_line = "HIRING DECISION: NOT RECOMMENDED (SECURITY)"
        elif not responses_adequate:
            status_text, status_color = ("NOT RECOMMENDED", C_DANGER)
            hire_line = "HIRING DECISION: NOT RECOMMENDED (RESPONSE ACCURACY BELOW PASSING BAR)"
        elif ov_score >= 8.5:
            status_text, status_color = ("STRONG HIRE SIGNAL", C_SUCCESS)
            hire_line = "HIRING DECISION: STRONG RECOMMENDATION"
        elif ov_score < 5.5:
            status_text, status_color = ("NOT RECOMMENDED", C_DANGER)
            hire_line = "HIRING DECISION: NOT RECOMMENDED (GAPS IDENTIFIED)"

        cand = (self.candidate_name or "Candidate").strip()
        try:
            st = getattr(self, 'start_time', None) or datetime.datetime.now()
            dt_str = st.strftime("%B %d, %Y")
            tm_str = st.strftime("%I:%M %p")
        except Exception:
            dt_str = datetime.datetime.now().strftime("%B %d, %Y")
            tm_str = datetime.datetime.now().strftime("%I:%M %p")

        # --- Cover / header (title + meta kept together to avoid orphan gaps) ---
        meta_rows = [
            [safe_para("<b>Candidate Name</b>", s_bold, True), safe_para(cand, s_norm, True)],
            [safe_para("<b>Interview Date</b>", s_bold, True), safe_para(dt_str, s_norm, True)],
            [safe_para("<b>Interview Time</b>", s_bold, True), safe_para(tm_str, s_norm, True)],
            [safe_para("<b>Total Questions</b>", s_bold, True), safe_para(str(len(evals_copy)), s_norm, True)],
            [safe_para("<b>Coding Problems</b>", s_bold, True), safe_para(str(coding_total), s_norm, True)],
            [safe_para("<b>Coding Correct</b>", s_bold, True), safe_para(f"{coding_passed}/{coding_total}" if coding_total else "0/0", s_norm, True)],
            [safe_para("<b>Integrity incidents (logged)</b>", s_bold, True), safe_para(str(unusual_ct), s_norm, True)],
            [safe_para("<b>Assessment Status</b>", s_bold, True), safe_para(status_text, s_norm, True)],
            [safe_para("<b>Overall Performance Score</b>", s_bold, True), safe_para(f"{ov_score:.1f}/10 ({pct_score}/100)", s_norm, True)],
        ]
        meta_tab = Table(meta_rows, colWidths=[2.15 * inch, 4.95 * inch])
        meta_tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), C_BG),
            ('BOX', (0, 0), (-1, -1), 0.75, C_BORDER),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, C_BORDER),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 11),
            ('RIGHTPADDING', (0, 0), (-1, -1), 11),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        story.append(
            KeepTogether(
                [
                    safe_para("OFFICIAL ASSESSMENT REPORT — CONFIDENTIAL", s_conf),
                    safe_para("AI CANDIDATE ASSESSMENT", s_main_title),
                    safe_para("Structured performance record", s_sub),
                    HRFlowable(width="100%", thickness=1, color=C_ACCENT, spaceAfter=8),
                    meta_tab,
                    gap_sm,
                ]
            )
        )

        badge_tab = Table([[safe_para(status_text.replace("/", " / "), s_badge)]], colWidths=[3.2 * inch])
        badge_tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), status_color),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(badge_tab)
        story.append(gap_md)

        # --- Executive summary ---
        story.append(safe_para("EXECUTIVE SUMMARY", s_head))
        sum_tab = Table([[safe_para(ai_summary, s_norm)]], colWidths=[7.1 * inch])
        sum_tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), C_WHITE),
            ('BOX', (0, 0), (-1, -1), 0.75, C_BORDER),
            ('PADDING', (0, 0), (-1, -1), 11),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(
            KeepTogether(
                [
                    safe_para(hire_line, s_bold, True),
                    gap_sm,
                    sum_tab,
                ]
            )
        )

        # --- Improvements & next steps ---
        story.append(gap_md)
        story.append(safe_para("KEY IMPROVEMENTS", s_head))
        imp_html = "<br/>".join("• " + str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') for x in improvements[:8])
        story.append(safe_para(imp_html if imp_html else "• Continue structured practice across weak areas.", s_norm, True))
        story.append(safe_para("RECOMMENDED NEXT STEPS", s_head))
        ns_html = "<br/>".join("• " + str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') for x in next_steps[:8])
        story.append(safe_para(ns_html if ns_html else "• Review feedback in the interaction log below.", s_norm, True))

        story.append(gap_md)
        # --- Performance scorecard (neat 2x2) ---
        sc_val = ParagraphStyle('ScVal', fontSize=16, textColor=C_MAIN, fontName='Helvetica-Bold', alignment=TA_CENTER)
        sc_sub = ParagraphStyle('ScSub', fontSize=7, textColor=C_MUTED, fontName='Helvetica', alignment=TA_CENTER)
        card = [
            [
                Table([[safe_para(f"{ov_score:.1f}", sc_val), safe_para("OVERALL PERFORMANCE", sc_sub)]], colWidths=[2.9 * inch]),
                Table([[safe_para(f"{avg_corr:.1f}", sc_val), safe_para("TECH ACCURACY", sc_sub)]], colWidths=[2.9 * inch]),
            ],
            [
                Table([[safe_para(f"{avg_fluency:.1f}", sc_val), safe_para("COMM. SCORE", sc_sub)]], colWidths=[2.9 * inch]),
                Table([[safe_para(f"{proctor_pct:.0f}%", sc_val), safe_para("TRUST / INTEGRITY", sc_sub)]], colWidths=[2.9 * inch]),
            ],
        ]
        sc_tab = Table(card, colWidths=[3.55 * inch, 3.55 * inch])
        sc_tab.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, C_BORDER),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, C_BORDER),
            ('BACKGROUND', (0, 0), (-1, -1), C_BG),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(KeepTogether([safe_para("PERFORMANCE SCORECARD", s_head), sc_tab]))

        # --- Visual summary charts (temp files removed after PDF build) ---
        try:
            _tf = tempfile.NamedTemporaryFile(delete=False, suffix="_perf.png")
            _tf.close()
            if self.create_performance_chart(_tf.name) and os.path.isfile(_tf.name):
                _chart_tmp.append(_tf.name)
                story.append(gap_sm)
                story.append(
                    KeepTogether(
                        [
                            safe_para("FIGURE 1 — PERFORMANCE BY MODULE (AVERAGE SCORE)", s_chart_cap),
                            Image(_tf.name, width=6.55 * inch, height=2.65 * inch),
                        ]
                    )
                )
        except Exception as _pe:
            print(f"[PDF] Performance chart skipped: {_pe}")
        try:
            _tf2 = tempfile.NamedTemporaryFile(delete=False, suffix="_pie.png")
            _tf2.close()
            if self.create_overall_pie_chart(_tf2.name) and os.path.isfile(_tf2.name):
                _chart_tmp.append(_tf2.name)
                story.append(gap_sm)
                story.append(
                    KeepTogether(
                        [
                            safe_para("FIGURE 2 — SCORE MIX BY DOMAIN (CONTRIBUTION)", s_chart_cap),
                            Image(_tf2.name, width=6.55 * inch, height=3.0 * inch),
                        ]
                    )
                )
        except Exception as _piee:
            print(f"[PDF] Pie chart skipped: {_piee}")
        if self.submitted_solutions:
            try:
                _tf3 = tempfile.NamedTemporaryFile(delete=False, suffix="_code.png")
                _tf3.close()
                if self.create_coding_chart(_tf3.name) and os.path.isfile(_tf3.name):
                    _chart_tmp.append(_tf3.name)
                    story.append(gap_sm)
                    story.append(
                        KeepTogether(
                            [
                                safe_para("FIGURE 3 — CODING ROUND RESULTS", s_chart_cap),
                                Image(_tf3.name, width=6.55 * inch, height=2.55 * inch),
                            ]
                        )
                    )
            except Exception as _ce:
                print(f"[PDF] Coding chart skipped: {_ce}")

        story.append(gap_md)
        # --- Primary integrity / unusual activity log (official record, not appendix-only) ---
        story.append(
            KeepTogether(
                [
                    safe_para("UNUSUAL ACTIVITY & SESSION INTEGRITY (PRIMARY LOG)", s_head),
                    safe_para(
                        "Includes automated proctoring detections and client-reported session events (e.g. tab visibility, fullscreen, "
                        "device-in-frame, face presence, multiple people, identity checks). Routine monitoring snapshots are omitted.",
                        s_small,
                    ),
                ]
            )
        )
        if not unusual_list:
            story.append(safe_para("No non-routine unusual activity was logged for this assessment.", s_norm))
        else:
            crit_ct = sum(1 for v in unusual_list if str(v.get("severity") or "").upper() == "CRITICAL")
            if crit_ct:
                story.append(safe_para(f"<b>Critical-level flags in this session: {crit_ct}</b>", s_bold, True))
            uh_rows = [
                [
                    safe_para("<b>Time</b>", s_bold, True),
                    safe_para("<b>Event</b>", s_bold, True),
                    safe_para("<b>Severity</b>", s_bold, True),
                    safe_para("<b>Description</b>", s_bold, True),
                    safe_para("<b>Evidence</b>", s_bold, True),
                ]
            ]
            for v in unusual_list[:48]:
                ts = str(v.get("timestamp") or "—").replace("T", " ")[:22]
                typ = str(v.get("type") or "—").replace("_", " ")
                sev = str(v.get("severity") or "—")
                msg = str(v.get("message") or "—")
                if len(msg) > 260:
                    msg = msg[:257] + "..."
                ev_cell = "Yes" if v.get("image_path") else "—"
                uh_rows.append([
                    safe_para(ts, s_small, True),
                    safe_para(typ, s_norm, True),
                    safe_para(sev, s_norm, True),
                    safe_para(msg, s_small, True),
                    safe_para(ev_cell, s_norm, True),
                ])
            uh_tab = Table(
                uh_rows,
                colWidths=[1.05 * inch, 1.35 * inch, 0.72 * inch, 3.0 * inch, 0.58 * inch],
                repeatRows=1,
            )
            uh_tab.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), C_MAIN),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.75, C_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, C_BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_BG]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(uh_tab)
            if len(unusual_list) > 48:
                story.append(safe_para(f"<i>…and {len(unusual_list) - 48} additional event(s); full history retained in system records.</i>", s_small, True))
        story.append(gap_md)

        # --- Technical skills analysis (summary rows) ---
        tech_acc_j = "Response correctness and depth across verbal interview modules."
        code_j = "Automated checks and rubric on submitted coding solutions." if coding_total else "No coding submissions recorded for this session."
        speech_j = "Verbal clarity, structure, and delivery (fluency proxy)."
        tsa_rows = [
            [safe_para("SKILL DOMAIN", s_bold, True), safe_para("SCORE", s_bold, True), safe_para("ASSESSMENT", s_bold, True), safe_para("JUSTIFICATION", s_bold, True)],
            [safe_para("Technical Accuracy", s_norm, True), safe_para(f"{avg_corr:.1f}/10", s_norm, True), safe_para(_band(avg_corr), s_norm, True), safe_para(tech_acc_j, s_small, True)],
            [safe_para("Coding Proficiency", s_norm, True), safe_para(f"{coding_avg:.1f}/10" if coding_total else "—", s_norm, True), safe_para(_band(coding_avg) if coding_total else "NOT ATTEMPTED", s_norm, True), safe_para(code_j, s_small, True)],
            [safe_para("Speech & Formulation", s_norm, True), safe_para(f"{avg_fluency:.1f}/10", s_norm, True), safe_para(_band(avg_fluency), s_norm, True), safe_para(speech_j, s_small, True)],
        ]
        tsa_tab = Table(tsa_rows, colWidths=[1.55 * inch, 0.85 * inch, 1.15 * inch, 3.55 * inch], repeatRows=1)
        tsa_tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), C_MAIN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.75, C_BORDER),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, C_BORDER),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9),
            ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        story.append(KeepTogether([safe_para("TECHNICAL SKILLS ANALYSIS", s_head), tsa_tab]))

        # --- By module (from evaluations) ---
        story.append(gap_sm)
        by_mod = defaultdict(list)
        for e in evals_copy:
            lab = str(e.get('type') or 'General').replace('_', ' ').title()
            by_mod[lab].append(self.sf(e.get('score', 0)))
        mod_rows = [[safe_para("Skill Area", s_bold, True), safe_para("Avg Score", s_bold, True), safe_para("Assessment", s_bold, True), safe_para("Justification", s_bold, True)]]
        for lab in sorted(by_mod.keys()):
            vals = by_mod[lab]
            m = sum(vals) / len(vals)
            fb = ""
            for ev in evals_copy:
                if str(ev.get('type') or 'General').replace('_', ' ').title() == lab and ev.get('feedback'):
                    fb = str(ev.get('feedback', ''))
                    break
            if len(fb) > 220:
                fb = fb[:217] + "..."
            mod_rows.append([
                safe_para(lab, s_norm, True),
                safe_para(f"{m:.1f}/10", s_norm, True),
                safe_para(_band(m), s_norm, True),
                safe_para(fb or "See interaction log for narrative feedback.", s_small, True),
            ])
        if len(mod_rows) == 1:
            mod_rows.append([safe_para("—", s_norm), safe_para("—", s_norm), safe_para("N/A", s_norm), safe_para("No evaluated responses.", s_small)])
        mod_tab = Table(mod_rows, colWidths=[1.55 * inch, 0.85 * inch, 1.15 * inch, 3.55 * inch], repeatRows=1)
        mod_tab.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), C_MAIN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.75, C_BORDER),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, C_BORDER),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_WHITE, C_BG]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9),
            ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        story.append(KeepTogether([safe_para("SKILLS ASSESSMENT (BY MODULE)", s_head), mod_tab]))

        # --- Strengths / weaknesses by module avg ---
        story.append(gap_sm)
        story.append(safe_para("STRENGTHS & WEAKNESSES ANALYSIS", s_head))
        avgs = [(lab, sum(v) / len(v)) for lab, v in by_mod.items()]
        avgs.sort(key=lambda x: x[1], reverse=True)
        strong = [f"{a[0]} (Avg: {a[1]:.1f}/10)" for a in avgs if a[1] >= 6][:5]
        weak = [f"{a[0]} (Avg: {a[1]:.1f}/10)" for a in avgs if a[1] < 6][:8]
        if not weak and avgs:
            weak = [f"{avgs[-1][0]} (Avg: {avgs[-1][1]:.1f}/10)"]
        sh = "<br/>".join("• " + x.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') for x in strong) or "• Insufficient data — continue assessments."
        wh = "<br/>".join("• " + x.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') for x in weak) or "• No weak areas flagged."
        story.append(safe_para("<b>STRONG IN:</b>", s_bold, True))
        story.append(safe_para(sh, s_norm, True))
        story.append(safe_para("<b>WEAK IN:</b>", s_bold, True))
        story.append(safe_para(wh, s_norm, True))

        # --- Interaction log (reference-style) ---
        if evals_copy:
            story.append(CondPageBreak(5.0 * inch))
            story.append(
                KeepTogether(
                    [
                        safe_para("INTERACTION LOG & TRANSCRIPTS", s_head),
                        safe_para("Verbatim candidate text as captured in-session.", s_small),
                    ]
                )
            )
            for i, ev in enumerate(evals_copy, 1):
                typ = str(ev.get('type', 'General')).upper().replace(' ', '_')
                q = ev.get('question', '') or ''
                va = (ev.get('verbatim_transcript') or ev.get('answer') or "").strip() or "(no response)"
                fb = ev.get('feedback', '') or '—'
                ov = self.sf(ev.get('score', 0))
                story.append(gap_sm)
                story.append(safe_para(f"<b>ROUND {i} | {typ}</b>", s_bold, True))
                story.append(safe_para(f"<b>INTERVIEWER:</b> {q}", s_norm, True))
                story.append(safe_para("<b>CANDIDATE RESPONSE:</b>", s_bold, True))
                story.append(Table([[safe_para(va, s_norm, True)]], colWidths=[7.1 * inch], style=TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), C_BG),
                    ('BOX', (0, 0), (-1, -1), 0.5, C_BORDER),
                    ('PADDING', (0, 0), (-1, -1), 9),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ])))
                story.append(safe_para(f"<b>JUSTIFICATION:</b> {fb}", s_norm, True))
                story.append(safe_para(f"<b>SCORE:</b> {ov:.0f}/10", s_bold, True))
                story.append(HRFlowable(width="100%", thickness=0.35, color=C_BORDER, spaceAfter=2))

        # Proctoring screenshots / proofs — all plans (appendix size scales with tier)
        tier_ev_cap = {0: 4, 1: 6, 2: 10, 3: 12, 4: 15}
        max_imgs = tier_ev_cap.get(int(plan_id), 8)
        self.collect_evidence()
        if self.evidence_images:
            story.append(CondPageBreak(3.4 * inch))
            story.append(
                KeepTogether(
                    [
                        safe_para("PROCTORING & FIDELITY LOG", s_head),
                        safe_para("Session-captured frames tied to monitoring events (all subscription tiers).", s_small),
                    ]
                )
            )
            ev_lbl_style = ParagraphStyle(
                'EvL', fontSize=8, alignment=TA_CENTER, fontName='Helvetica-Bold', textColor=C_MUTED, leading=10
            )
            for i in range(0, len(self.evidence_images[:max_imgs]), 3):
                chunk = self.evidence_images[i : i + 3]
                img_row, lbl_row = [], []
                for img_p, lbl in chunk:
                    try:
                        if os.path.exists(img_p):
                            img_row.append(Image(img_p, width=2.2 * inch, height=1.55 * inch))
                            lbl_row.append(safe_para(lbl, ev_lbl_style))
                    except Exception:
                        continue
                while len(img_row) < 3:
                    img_row.append(Spacer(2.2 * inch, 1.55 * inch))
                    lbl_row.append(RLParagraph("", ev_lbl_style))
                if not any(isinstance(c, Image) for c in img_row):
                    continue
                ev_blk = Table(
                    [img_row, lbl_row],
                    colWidths=[2.35 * inch] * 3,
                )
                ev_blk.setStyle(
                    TableStyle(
                        [
                            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.append(ev_blk)
                story.append(gap_sm)

        try:
            doc.build(story)
        finally:
            for _cp in _chart_tmp:
                try:
                    if os.path.isfile(_cp):
                        os.unlink(_cp)
                except Exception:
                    pass
        return True

    def collect_evidence(self):
        """Finds evidence images for this session (proctor proofs under evidence/, scoped by session id)."""
        scan_dir = os.path.join(os.getcwd(), "evidence")
        if hasattr(self, "evidence_path") and self.evidence_path:
            if os.path.isdir(self.evidence_path):
                scan_dir = self.evidence_path
            elif os.path.isfile(self.evidence_path) and os.path.isdir(scan_dir):
                pass
        if not os.path.isdir(scan_dir):
            self.evidence_images = []
            return []

        sid = str(getattr(self, "session_id", "") or "")
        pfx = f"proof_{sid}_" if sid else None

        found = []
        try:
            for f in os.listdir(scan_dir):
                if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                if pfx and not f.startswith(pfx):
                    continue
                full_path = os.path.join(scan_dir, f)
                if not os.path.isfile(full_path):
                    continue
                label = "Monitor Flag"
                fl = f.lower()
                if "multi_face" in fl or "multiple" in fl:
                    label = "Multiple Faces"
                elif "no_face" in fl or "no_person" in fl:
                    label = "No Face Detected"
                elif "phone" in fl or "gadget" in fl or "cheating" in fl:
                    label = "Device Usage"
                elif "looking_away" in fl:
                    label = "Attention Warning"
                elif "identity" in fl:
                    label = "Identity Proof"
                found.append((full_path, label))

            found.sort(key=lambda x: x[0])
            self.evidence_images = found
            return found
        except Exception as e:
            print(f"Error collecting evidence: {e}")
            self.evidence_images = []
            return []

    def cleanup_session(self):
        """Removes sensitive files (resume, proctoring images) from the server to save space and ensure privacy."""
        # 1. Delete Candidate Resume
        if hasattr(self, 'resume_path') and self.resume_path and os.path.exists(self.resume_path):
            try:
                # Close any potential hooks if any library was holding it (unlikely but safe)
                os.remove(self.resume_path)
                print(f"🗑️ [CLEANUP] Deleted resume: {os.path.basename(self.resume_path)}")
                self.resume_path = None
            except Exception as e:
                print(f"⚠️ [CLEANUP] Could not delete resume: {e}")
        
        # 2. Delete Procting Evidence Folder
        if hasattr(self, 'evidence_path') and self.evidence_path and os.path.exists(self.evidence_path):
            try:
                import shutil
                shutil.rmtree(self.evidence_path)
                print(f"🗑️ [CLEANUP] Deleted evidence folder: {self.evidence_path}")
                self.evidence_path = None
            except Exception as e:
                print(f"⚠️ [CLEANUP] Could not delete evidence: {e}")
        
        # 3. Clear transient image data
        self.evidence_images = []
        self.candidate_photo = None
    def analyze_coding_submission(self, submission):
        """
        Generates deep analysis for a coding submission using LLM.
        Returns a dictionary with structured feedback.
        """
        if not self.client:
            return {
                "breakdown": {"Correctness": 5, "Algorithm": 5, "Time Complexity": 5, "Space Complexity": 5, "Edge Cases": 5, "Code Quality": 5},
                "strengths": ["Code submitted successfully."],
                "improvements": ["Review logic for edge cases."],
                "feedback": "Detailed analysis unavailable in offline mode."
            }
        code = submission.get('code', '')
        title = submission.get('title', 'Unknown Problem')
        lang = submission.get('language', 'Unknown')
        prompt = f"""
        Act as a Senior Technical Interviewer. Analyze this candidate's code submission.
        Problem: {title}
        Language: {lang}
        Candidate's Code:
        ```
        {code[:3000]}
        ```
        Task: Provide a strict, critical assessment in JSON format.
        1. Evaluate 6 metrics (1-10 scores): Correctness, Algorithm, Time Complexity, Space Complexity, Edge Cases, Code Quality.
        2. "strengths": List 2-3 specific good points.
        3. "improvements": List 2-3 specific areas to improve (variable naming, efficiency, edge cases).
        4. "feedback": A 3-4 sentence professional summary of the code quality and approach.
        Return JSON ONLY:
        {{
            "breakdown": {{
                "Correctness": int,
                "Algorithm": int,
                "Time Complexity": int,
                "Space Complexity": int,
                "Edge Cases": int,
                "Code Quality": int
            }},
            "strengths": ["point 1", "point 2"],
            "improvements": ["point 1", "point 2"],
            "feedback": "summary text"
        }}
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            json_str = re.search(r"\{.*\}", response.choices[0].message.content, re.DOTALL).group()
            return json.loads(json_str)
        except Exception as e:
            print(f"Coding Analysis Error: {e}")
            return {
                "breakdown": {"Correctness": 0, "Algorithm": 0, "Time Complexity": 0, "Space Complexity": 0, "Edge Cases": 0, "Code Quality": 0},
                "strengths": ["Could not analyze."],
                "improvements": ["System error during analysis."],
                "feedback": "Analysis failed."
            }

    def generate_question(self, category='general', previous_answer=None):
        """Dynamic question generation based on real-time evaluation and resume parsing."""
        if not hasattr(self, 'model_name') or self.model_name == "llama-3.1-8b-instant":
            self.model_name = "llama-3.3-70b-versatile"
        self.current_category = category
        with self.lock:
            # Shared State Critical Section
            history_copy = list(self.history)
            previous_questions = [h.get('question') for h in history_copy if h.get('question')]
            eval_copy = list(self.evaluations)
            asked_topics_copy = list(self.asked_topics)
            resume_text_copy = self.resume_text
            candidate_name_copy = self.candidate_name
        if not self.resume_text or not self.client:
            # Category-aware fallback even in offline mode
            fallbacks = {
                'greeting': [f"Hello {self.candidate_name}. Welcome to your interview! How are you doing today?"],
                'warmup': [
                    "Great to have you here. Did you face any issues while reaching or connecting today?",
                    "How has your day been treating you so far?"
                ],
                'intro': ["To get us started, could you please provide a brief introduction about yourself and your background?"],
                'resume_overview': ["From what you wrote on your resume, how do your strongest project and your top skill reinforce each other for the role you want?"],
                'resume_skills': ["Pick one skill you explicitly listed on your resume and describe a situation where you used it hands-on—what was the outcome?"],
                'resume_projects': ["Choose one project title from your resume and explain your personal contribution and the main technologies you used there."],
                'technical_core': ["Let's dive into some core concepts. How do you ensure your code is both efficient and maintainable in a production environment?"],
                'technical_advanced': ["Moving to advanced topics, what are your thoughts on modern system design patterns and how do you choose between them?"],
                'scenario_technical': [
                    "Imagine the production version of your strongest resume project goes down at peak traffic. What is your first 10 minutes of response?",
                    "Pick a skill you list on your resume: how would you apply it if a stakeholder asked for a same-day hotfix that might introduce tech debt?"
                ],
                'coding': [
                    "Let's transition to the coding round. Please check the editor for your first challenge. Good luck!",
                    "Now, let's move on to the second coding problem. You're doing well, please proceed."
                ],
                'code': [
                    "Let's transition to the coding round. Please check the editor for your first challenge. Good luck!",
                    "Now, let's move on to the second coding problem. You're doing well, please proceed."
                ],
                'case_study': [
                    "Let's look at a scenario. If you were task with scaling an application for millions of users, what would be your first steps?",
                    "How would you approach designing a system that requires extremely high availability?"
                ],
                'scenario_behavioral': ["Can you describe a situation where you had to adapt quickly to a major change in project scope or direction?"],
                'leadership': ["Have you ever had to lead a task or mentor a peer? How did you handle that responsibility and what was the outcome?"],
                'scenario_hr': ["Suppose you have a very tight deadline for a project. How do you manage your tasks and stress in such a situation?"],
                'teamwork': ["Tell me about your experience working in a team. How do you handle disagreements with colleagues?"],
                'adaptability': ["Tell me about a time when you received critical feedback. How did you process it and what changes did you make?"],
                'future_goals': ["Where do you see yourself in the next three to five years, and how does this role align with your professional goals?"],
                'conclusion': ["Thank you for participating in the interview. We will evaluate your responses and get back to you soon. Have a great day!"]
            }
            opts = fallbacks.get(category, ["Could you please tell me more about your recent professional experience?"])
            # Avoid repetition
            for opt in opts:
                if opt not in previous_questions:
                    with self.lock:
                        self.history.append({"question": opt, "category": category, "topic": "Fallback"})
                    return opt
            with self.lock:
                self.history.append({"question": opts[-1], "category": category, "topic": "Fallback"})
            return opts[-1]
        # 1. ADAPTIVE DIFFICULTY LOGIC
        avg_score = 0
        if eval_copy:
            avg_score = sum([e.get('score', 0) for e in eval_copy]) / len(eval_copy)
        # Difficulty Buckets: < 4 (Basic), 5-7 (Intermediate), > 8 (Expert/Arch)
        if avg_score < 4.5:
            difficulty_instruction = "Difficulty Level: BASIC/FUNDAMENTAL. The candidate is struggling; ask clear, foundational questions."
        elif avg_score >= 8.0:
            difficulty_instruction = "Difficulty Level: ADVANCED/ARCHITECTURE. The candidate is performing exceptionally; ask about implementation details, trade-offs, and system design."
        else:
            difficulty_instruction = "Difficulty Level: INTERMEDIATE. Focus on practical application and conceptual understanding."
        # Keep resume text within safe LLM limits (more context for resume-only rounds)
        trimmed_resume = resume_text_copy[:5500] if resume_text_copy else ""
        resume_for_prompt = trimmed_resume[:5000] if category in ('resume_skills', 'resume_projects', 'resume_overview') else trimmed_resume[:3000]
        # 2. STEP-BASED CATEGORIZATION (Strict 9-Step Flow)
        if category == 'greeting':
            context = "Step 1: Greeting"
            nm = candidate_name_copy or self.candidate_name or "the candidate"
            context_instruction = (
                f"Greet {nm} professionally using a time-appropriate opener (good morning, good afternoon, or good evening). "
                f"Then ask exactly ONE short welcoming question—such as how they are doing today or if they feel ready to begin. "
                f"Keep the whole utterance brief and natural."
            )
            self.current_topic = "Greeting"
        elif category == 'warmup':
            context = "Step 2: Basic warm-up (human rapport)"
            warmup_options = [
                "How has your day been so far?",
                "Did everything go smoothly getting set up for this session?",
                "Is there anything you need before we move into deeper questions?"
            ]
            remaining = [o for o in warmup_options if o not in previous_questions]
            topic_to_ask = remaining[0] if remaining else random.choice(warmup_options)
            context_instruction = (
                f"Continue building rapport: acknowledge any prior reply briefly, then naturally steer into: {topic_to_ask} "
                f"Keep it conversational—no interview 'grilling' yet."
            )
            self.current_topic = "Warm-up"
        elif category == 'intro':
            context = "Step 3: Self Introduction (MANDATORY)"
            context_instruction = "Ask the candidate: 'Please introduce yourself.' (MANDATORY)"
            self.current_topic = "Self Introduction"
        elif category in ('resume_skills', 'resume_projects', 'resume_overview'):
            # Strictly grounded in the candidate's resume text and extracted entities
            skills_list = list(self.skills_mentioned or [])
            tech_list = list(self.technologies_mentioned or [])
            proj_list = list(self.projects_mentioned or [])
            subj_list = list(self.core_subjects or [])
            if self.module_topic:
                context = f"Resume: {category} [module context: {self.module_topic}]"
            else:
                context = f"Resume: {category.replace('_', ' ').title()}"
            all_topics = []
            if category == 'resume_skills':
                all_topics = [f"Skill: {s}" for s in skills_list] + [f"Tool/Tech: {t}" for t in tech_list]
                all_topics += [f"Subject: {s}" for s in subj_list[:8]]
                if not all_topics:
                    all_topics = ["Items explicitly named in the resume text (languages, frameworks, tools, coursework)"]
                _pack = ", ".join((skills_list + tech_list + subj_list)[:22]) or "(read from RESUME TEXT only)"
                context_instruction = (
                    "Ask exactly ONE question that drills something the candidate actually listed on their resume—"
                    "a language, framework, library, tool, platform, or course topic they wrote down. "
                    "Name that item in your question. Forbidden: generic skill questions not tied to their CV; do not invent tools they did not list. "
                    f"Prefer these extracted targets when present: {_pack}."
                )
            elif category == 'resume_projects':
                if proj_list:
                    all_topics = [f"Project: {p}" for p in proj_list]
                else:
                    all_topics = ["Work experience or project titles literally present in the resume text"]
                context_instruction = (
                    "Ask exactly ONE question about a specific project, internship, product, or research line they documented on their resume—"
                    "their role, stack used, trade-off, metric, or hardest bug. Name the project from their CV. "
                    "Forbidden: hypothetical projects not on the resume."
                )
            else:
                # resume_overview — ties together what they wrote (after skills & project rounds)
                all_topics = [f"Project: {p}" for p in proj_list[:5]] + [f"Skill: {s}" for s in skills_list[:6]]
                if not all_topics:
                    all_topics = ["How the roles and bullets on their resume form a coherent story"]
                context_instruction = (
                    "Ask exactly ONE question that connects pieces they actually wrote on their resume—"
                    "for example how a listed project used a named skill, or how education supports their stated objective. "
                    "It must reference concrete items from RESUME TEXT (company, project title, stack, course). No generic 'tell me about yourself'."
                )
            remaining = [t for t in all_topics if t not in asked_topics_copy]
            if remaining:
                topic_to_ask = remaining[0]
            else:
                shuffled_all = list(all_topics)
                random.shuffle(shuffled_all)
                topic_to_ask = shuffled_all[0]
            self.current_topic = topic_to_ask
        elif category in ('technical_core', 'technical_advanced', 'resume', 'technical'):
            # MODALITY OVERRIDE: If a specialized Assessment Module (Topic) is selected, prioritize it!
            if self.module_topic:
                context = f"Step: {category.upper()} [SPECIALIZED MODULE: {self.module_topic}]"
            else:
                context = f"Step: {category.upper().replace('_', ' ')}"
            all_topics = []
            # Module-Specific Topic Injection
            if self.module_topic:
                module_mapping = {
                    'Technical Core': ["Fundamental Logic", "Data Structures Efficiency", "Algorithm Choices", "Big O Complexity"],
                    'System Design': ["Microservices Architecture", "Load Balancing Strategies", "Database Sharding", "Caching Layers", "API Rate Limiting"],
                    'HR & Leadership': ["Conflict Resolution", "Strategic Vision", "Mentorship Experience", "Handling Resistance"],
                    'Data Intelligence': ["Neural Network Architecture", "Feature Engineering", "Data Pipeline Scalability", "Model Evaluation Metrics"],
                    'Project Deep-Dive': ["Detailed Architecture Walkthrough", "Technical Trade-offs", "Production Challenges", "Security Implementation"],
                    'Frontend Mastery': ["Web Performance Optimization", "State Management Patterns", "CSS/Layout Engineering", "React/Framework Internals"]
                }
                # If specific mapping exists, use it. Else use the topic string itself.
                module_topics = module_mapping.get(self.module_topic, [self.module_topic])
                all_topics.extend(module_topics)
            # Mix resume signals when still in technical rounds (helps continuity)
            if getattr(self, 'projects_mentioned', None):
                all_topics.extend([f"Project: {p}" for p in self.projects_mentioned[:4]])
            if getattr(self, 'skills_mentioned', None):
                all_topics.extend([f"Skill: {s}" for s in self.skills_mentioned[:6]])
            if getattr(self, 'technologies_mentioned', None):
                all_topics.extend([f"Technology: {t}" for t in self.technologies_mentioned[:6]])
            if 'advanced' in category:
                all_topics = ["System Architecture", "Performance Optimization", "Scalability Patterns", "Security Best Practices", "Distributed Systems"]
            # SMART FALLBACK: If no topics found in resume, use diversified technical areas
            if not all_topics:
                fallback_tech_areas = [
                    "Problem Solving Approach", "Code Quality & Maintenance",
                    "Team Collaboration in Tech", "Learning New Technologies",
                    "Debugging Strategies", "System Reliability", "Scalability Concepts",
                    "Version Control Best Practices", "Testing Philosophy"
                ]
                all_topics = fallback_tech_areas
            remaining = [t for t in all_topics if t not in asked_topics_copy]
            # Prioritize fresh topics, then shuffle remaining to avoid predictable loops
            if remaining:
                topic_to_ask = remaining[0]
            else:
                shuffled_all = list(all_topics)
                random.shuffle(shuffled_all)
                topic_to_ask = shuffled_all[0]
            context_instruction = f"Generate a unique technical question about: {topic_to_ask}. DO NOT ask for a general 'tell me about your background'. Ask a specific 'How would you...' or 'Explain a time...' question."
            self.current_topic = topic_to_ask
        elif category == 'scenario_technical':
            context = "Resume-grounded technical scenario"
            skills_snip = ", ".join((self.skills_mentioned or [])[:14]) or "their core skills from the resume"
            proj_snip = ", ".join((self.projects_mentioned or [])[:8]) or "their listed projects"
            context_instruction = (
                f"Ask ONE focused scenario question that ties directly to the candidate's resume: skills such as [{skills_snip}] "
                f"and projects such as [{proj_snip}]. "
                f"Pose a realistic situation (incident response, scaling choice, bug triage, API breakage, deadline conflict) and ask what they would do first and why. "
                f"Do not ask them to summarize the resume—test judgment and depth."
            )
            self.current_topic = "Scenario (resume-based)"
        elif category == 'case_study':
            context = "Step 6: Case Study Questions"
            case_options = ["Scalability (Millions of users)", "Debugging (Production failure)", "API Design", "Data Consistency in Distributed Systems"]
            remaining = [o for o in case_options if o not in previous_questions]
            topic_to_ask = remaining[0] if remaining else random.choice(case_options)
            context_instruction = f"Ask a short real-world case study question related to {topic_to_ask}. Focus on technical thinking and problem-solving."
            self.current_topic = f"Case Study: {topic_to_ask}"
        elif category in ['behavioral', 'scenario_behavioral', 'scenario_hr', 'leadership', 'adaptability', 'teamwork', 'future_goals']:
            # HR MODULE OVERRIDE
            if self.module_topic == 'HR & Leadership':
                context = f"Phase: {category.upper()} [SPECIALIZED HR MODULE]"
                topic_options = {
                    'behavioral': ["Strategic Decision Making", "Handling Team Resistance", "Visionary Leadership"],
                    'scenario_behavioral': ["Budget/Resource Crisis", "Interpersonal Conflict", "Organizational Change"],
                    'leadership': ["Defining Technical Roadmaps", "Delegation Philosophy", "Building Engineering Culture"],
                    'teamwork': ["Stakeholder Negotiation", "Cross-team Collaboration"],
                    'future_goals': ["Professional Legacy", "Building Scalable Teams"]
                }
            else:
                context = f"Phase: {category.upper().replace('_', ' ')}"
                topic_options = {
                    'behavioral': ["Handling pressure", "Dealing with failure", "Learning from mistakes"],
                    'scenario_behavioral': ["Adapting to change", "Complex decision making", "Conflict with stakeholders"],
                    'scenario_hr': ["Company culture fit", "Long-term commitment", "Motivation"],
                    'leadership': ["Mentoring others", "Taking initiative", "Project ownership"],
                    'adaptability': ["Learning new tech", "Fast-paced environment"],
                    'teamwork': ["Collaborative coding", "Receiving feedback", "Team communication"],
                    'future_goals': ["Career growth", "Technical mastery", "Contribution to the field"]
                }
            # Use specific options if mapped, else default
            current_options = topic_options.get(category, ["Professional growth", "Team collaboration"])
            remaining = [o for o in current_options if o not in asked_topics_copy]
            topic_to_ask = remaining[0] if remaining else random.choice(current_options)
            context_instruction = f"Ask a {category.replace('_', ' ')} question about: {topic_to_ask}. Focus on real-world impact and candidate's specific behavior."
            self.current_topic = topic_to_ask
        elif category in ('code', 'coding'):
            with self.lock:
                coding_count = sum(1 for h in self.history if h.get('category') in ('code', 'coding'))
                self.current_topic = f"Coding Problem {coding_count + 1}"
                if coding_count == 0:
                    msg = "Let's move to the coding section. Please use the on-screen editor for your first problem when you're ready."
                else:
                    msg = "Great progress. When you're ready, please work through the second coding problem in the editor."
                self.history.append({"question": msg, "category": "code", "topic": self.current_topic})
            return msg
        elif category == 'conclusion':
            context = "Final Step: Conclusion"
            context_instruction = "Politely conclude the interview. Example: 'Thank you for participating. We will evaluate your responses.'"
            self.current_topic = "Conclusion"
        else:
            context = "Interview Interaction"
            context_instruction = "Continue the conversation naturally based on the interview progress."
            self.current_topic = "General"
        # 3. LLM PROMPT WITH STRICT MANDATE
        prompt = f"""
        Act as "Atlas", a professional senior-level male Technical Interviewer.
        Your persona is calm, authoritative but encouraging, and strictly masculine in tone and address.
        Generate a concise, natural-sounding interview question.
        CATEGORY: {category}
        TOPIC: {getattr(self, 'current_topic', 'General')}
        KNOWLEDGE CONTEXT: {context}
        # TRANSITION GUARD:
        # If this is the FIRST question of a new category, start with a professional transition.
        # Check if the previous question was in a different category.
        {f"TRANSITION REQUIRED: You are moving to a new part of the interview. Use a professional transition phrase like 'Moving on...' or 'Next, I'd like to ask...' before your question. DO NOT mention internal category names like '{category.upper()}' to the candidate." if self.history and self.history[-1]['category'] != category else ""}
        INSTRUCTION: {context_instruction}
        STRICT INTERACTION RULES:
        1. BE INTERACTIVE: If there is a "PREVIOUS ANSWER", you MUST acknowledge it warmly and naturally before asking the next question (e.g., "That sounds interesting," "I see," "Great point. Now..."). THIS IS VERY IMPORTANT.
        2. NO EVALUATION FEEDBACK: Do NOT tell the candidate if they are right or wrong. Do NOT give feedback on technical correctness. Just acknowledge conversationally.
        3. STRICT ORDER AND QUESTIONS: Ask ONLY ONE question at a time. Do not stack questions.
        4. NEVER REPEAT: Ensure the question is entirely different from the PREVIOUS QUESTIONS.
        5. BREVITY: Keep the response natural and under 40 words total.
        PREVIOUS ANSWER GIVEN BY CANDIDATE: {previous_answer if previous_answer else 'None provided or start of interview'}
        PREVIOUS QUESTIONS ALREADY ASKED: {previous_questions}
        RESUME TEXT: {resume_for_prompt}
        Return ONLY the exact text to be spoken by the interviewer. Do NOT wrap in quotes. No technical feedback. No acknowledgement like "Correct".
        Acknowledgement allowed ONLY if "PREVIOUS ANSWER" is provided (e.g., "Interesting point...").
        """
        try:
            # 3. LLM INVOCATION WITH REPETITION GUARD
            for attempt in range(3): # Max 3 attempts to get a non-duplicate
                try:
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.85, # Slightly higher for more variety
                        max_tokens=150
                    )
                    question_text = response.choices[0].message.content.strip().strip('"').strip()
                    # Prefix cleanup
                    if ":" in question_text[:20]:
                        question_text = question_text.split(":", 1)[1].strip()
                    # SEMANTIC REPETITION CHECK
                    is_duplicate = False
                    q_clean = re.sub(r'[^a-zA-Z0-9]', '', question_text.lower())
                    for prev in previous_questions:
                        prev_clean = re.sub(r'[^a-zA-Z0-9]', '', str(prev).lower())
                        # Check for high similarity or containment
                        if q_clean in prev_clean or prev_clean in q_clean or len(q_clean) < 15:
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        break # Success!
                    else:
                        print(f"ð LLM Repeat Detected (Attempt {attempt+1}). Regenerating...")
                        # Update prompt for retry
                        prompt += "\n\nCRITICAL: The previous suggestion was a duplicate. You MUST generate a different question NOW."
                except Exception as e:
                    print(f"â Attempt {attempt+1} failed: {e}")
                    if attempt == 2: raise e
            # Track results
            with self.lock:
                if hasattr(self, 'current_topic') and self.current_topic not in self.asked_topics:
                    self.asked_topics.append(self.current_topic)
                self.history.append({"question": question_text, "category": category, "topic": getattr(self, 'current_topic', 'General')})
            return question_text
        except Exception as e:
            print(f"â Question Generation Error: {e}")
            fallback_options = [
                f"Could you elaborate on your experience with {getattr(self, 'current_topic', 'your core technologies')}?",
                f"Can you walk me through a complex problem you solved while working on {getattr(self, 'current_topic', 'your projects')}?",
                "What were the most significant technical challenges you faced in your most recent project?",
                f"How would you approach optimizing the performance of a task related to {getattr(self, 'current_topic', 'your field')}?",
                "Can you tell me more about your recent technical background?"
            ]
            # Repetition prevention in exception fallback too
            for opt in fallback_options:
                if opt not in previous_questions:
                    with self.lock:
                        self.history.append({"question": opt, "category": category, "topic": "Critical Fallback"})
                    return opt
            with self.lock:
                self.history.append({"question": fallback_options[-1], "category": category, "topic": "Critical Fallback"})
            return fallback_options[-1]

    

    def evaluate_answer(self, question, answer):
        """Evaluate the answer with CFK metrics; stores verbatim transcript for reports."""
        # --- ICEBREAKER HANDLING REMOVED ---
        # Guard clause: Do not evaluate if question is missing
        if not question or not question.strip():
            return {"score": 0, "feedback": "System Error: Missing Question", "ignore": True}
        verbatim = (answer if isinstance(answer, str) else str(answer or "")).strip()
        # Taking "whatever they say" - removing strict 3-word filter and negative trigger zero-marks
        # Even short answers or "I don't know" will now be passed to the LLM for a natural conversational transition
        if not verbatim:
            result = {
                "score": 0,
                "confidence": 0,
                "fluency": 0,
                "knowledge": 0,
                "correctness": 0,
                "correctness_score": 0,
                "feedback": "No response provided by the candidate.",
                "question": question,
                "answer": "No response",
                "verbatim_transcript": "",
                "type": getattr(self, 'current_category', "General"),
                "grammar_issues": "N/A"
            }
            with self.lock:
                self.evaluations.append(result)
            return result
        prompt = f"""
        Evaluate this interview answer.
        IMPORTANT: This text is a raw transcript from a browser's Speech-to-Text engine.
        It WILL have missing punctuation, phonetic errors (e.g., 'React JS' might be 'react choice', 'API' might be 'e-p-i'), and run-on sentences.
        TASK:
        1. RECOVER MEANING (CRITICAL): The candidate may be speaking in a LOW PITCH or LOW VOLUME. The transcript might be extremely whisper-like or fragmented. Extract EVERY technical keyword and intent even from single syllables.
        2. HIGH TOLERANCE: Do NOT penalize for "Noisy" or "Broken" text. These are expected due to low-volume capture. Focus on the raw intelligence of the response.
        3. BIAS TOWARDS CANDIDATE: If you detect even a hint of the correct technical concept, assume knowledge and give credit.
        4. "fluency" should measure the LOGICAL FLOW, not the capture quality.
        5. "confidence" should be derived from the correctness, NOT the loudness or text volume.
        6. "correctness" (0-10): factual and logical correctness of the answer relative to the question asked (not transcript polish).
        7. Provide "feedback" that summarizes their technical strength.
        8. In "grammar_issues", list only MAJOR technical misstatements. Ignore all phonetic and transcription errors.
        Question: {question}
        Answer (verbatim): {verbatim[:8000]}
        Return JSON ONLY:
        {{
            "score": 0-10,
            "correctness": 0-10,
            "accuracy": 0-10,
            "depth": 0-10,
            "clarity": 0-10,
            "confidence": 0-10,
            "fluency": 0-10,
            "knowledge": 0-10,
            "feedback": "Constructive, professional feedback analyzing the candidate's answer strength.",
            "grammar_issues": "Major technical misstatements only."
        }}
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300
            )
            json_str = re.search(r"\{.*\}", response.choices[0].message.content, re.DOTALL).group()
            result = json.loads(json_str)
            # Ensure full data structure is returned
            result['question'] = question
            result['answer'] = verbatim
            result['verbatim_transcript'] = verbatim
            result['type'] = self.current_category if hasattr(self, 'current_category') else "General"
            # Defaults if missing
            if 'confidence' not in result: result['confidence'] = 5
            if 'fluency' not in result: result['fluency'] = 5
            if 'accuracy' not in result: result['accuracy'] = result.get('score', 5)
            if 'correctness' not in result: result['correctness'] = result.get('accuracy', result.get('score', 5))
            if 'depth' not in result: result['depth'] = 5
            if 'clarity' not in result: result['clarity'] = 5
            if 'knowledge' not in result: result['knowledge'] = result.get('score', 5)
            result['correctness_score'] = float(self.sf(result.get('correctness', result.get('accuracy', result.get('score', 0)))))
            # CRITICAL: Store in object state for tracking and reports
            with self.lock:
                self.evaluations.append(result)
            # UPDATE HISTORY for Adaptive Follow-ups
            # Find the last entry in history with this question and attach the answer
            for entry in reversed(self.history):
                if entry.get('question') == question:
                    entry['answer'] = verbatim
                    entry['verbatim_transcript'] = verbatim
                    break
            return result
        except Exception as _eval_err:
            print(f"[WARN] evaluate_answer fallback: {_eval_err}")
            fb = {
                "score": 5,
                "confidence": 5,
                "fluency": 5,
                "knowledge": 5,
                "accuracy": 5,
                "correctness": 5,
                "correctness_score": 5.0,
                "depth": 5,
                "clarity": 5,
                "feedback": "Could not evaluate automatically.",
                "grammar_issues": "N/A",
                "question": question,
                "answer": verbatim,
                "verbatim_transcript": verbatim,
                "type": getattr(self, 'current_category', "General"),
            }
            with self.lock:
                self.evaluations.append(fb)
            for entry in reversed(self.history):
                if entry.get('question') == question:
                    entry['answer'] = verbatim
                    entry['verbatim_transcript'] = verbatim
                    break
            return fb

    # --- NEW: LIGHTWEIGHT IDENTITY VERIFICATION (OPENCV ONLY) ---

    def _get_face_histogram(self, img, is_profile=False):
        """
        Lightweight face detection and histogram extraction.
        Uses Haarcascades for speed.
        """
        try:
            import cv2
            import numpy as np

            # 1. Convert to grayscale for detection and histogram
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # 2. Use Haarcascade for face detection
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            cascade_path_alt = cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
            
            face_cascade = cv2.CascadeClassifier(cascade_path)
            face_cascade_alt = cv2.CascadeClassifier(cascade_path_alt)
            
            # Relax settings for profile photos which might be low-res or unusual poses
            scale_factor = 1.05 if is_profile else 1.1
            min_neighbors = 3 if is_profile else 5
            
            # Detect faces
            faces = face_cascade.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=(30, 30))
            
            if len(faces) == 0:
                print("⚠️ [FACE] Primary cascade failed. Trying alt2 cascade...")
                faces = face_cascade_alt.detectMultiScale(gray, scaleFactor=scale_factor, minNeighbors=min_neighbors, minSize=(30, 30))
            
            if len(faces) == 0:
                print(f"❌ [FACE] Detection failed (is_profile={is_profile}).")
                return None

            # 3. Focus on the largest face (most likely the candidate)
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            (x, y, w, h) = faces[0]
            face_roi = gray[y:y+h, x:x+w]

            # 4. Compute and normalize histogram
            hist = cv2.calcHist([face_roi], [0], None, [256], [0, 256])
            cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
            
            return hist
        except Exception as e:
            print(f"❌ [FACE] Histogram extraction error: {e}")
            return None

    def get_face_encoding_from_base64(self, photo_data):
        """
        Extracts face identity baseline from base64 OR file path.
        """
        if not photo_data:
            return None

        try:
            import base64
            import numpy as np
            import cv2
            import os
            
            img = None
            
            # 1. Check if it's a file path
            if isinstance(photo_data, str) and len(photo_data) < 500 and os.path.exists(photo_data):
                img = cv2.imread(photo_data)
                if img is not None:
                    print(f"✅ [FACE] Loaded profile from file: {photo_data}")
            
            # 2. Decode as Base64 if not yet loaded
            if img is None:
                if "," in photo_data:
                    photo_data = photo_data.split(",")[1]
                
                # Clean up any potential whitespace/meta-chars
                photo_data = photo_data.strip()
                
                img_data = base64.b64decode(photo_data)
                nparr = np.frombuffer(img_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                print("❌ [FACE] Failed to decode profile image data.")
                return None
            
            # Extract Histogram with Profile settings (Aggressive detection)
            hist = self._get_face_histogram(img, is_profile=True)
            if hist is not None:
                self.profile_face_hist = hist
                print("✅ [FACE] Profile identity baseline established (Lightweight).")
                return True
            
            print("❌ [FACE] No face found in candidate's profile photo.")
            return None
        except Exception as e:
            print(f"❌ [FACE] Profile prep error: {e}")
            return None

    def verify_face_match(self, frame):
        """
        Compare live camera face to the profile-photo histogram (HISTCMP_CORREL).
        Higher = more similar. Reject low scores so a different person cannot pass as the account holder.
        Override strictness with env FACE_MATCH_MIN_CORREL (default 0.58).
        """
        if self.profile_face_hist is None:
            return False, "Profile image missing"

        if frame is None:
            return False, "Live camera feed lost"

        try:
            import cv2
            import numpy as np

            # 1. Extract histogram from live frame
            live_hist = self._get_face_histogram(frame)
            
            if live_hist is None:
                print("❌ [FACE] Identity Verification Failed: No face detected in camera.")
                return False, "Face not detected in camera"
                
            # 2. Histogram correlation: 1.0 ~ same lighting/shape distribution; <<0.5 different person/lighting
            similarity = cv2.compareHist(self.profile_face_hist, live_hist, cv2.HISTCMP_CORREL)
            min_correl = float(os.environ.get("FACE_MATCH_MIN_CORREL", "0.58"))

            if similarity >= min_correl:
                print(f"✅ [FACE] Identity verified vs profile (score={similarity:.4f}, min={min_correl})")
                return True, "Match success"
            print(f"❌ [FACE] Identity mismatch (score={similarity:.4f} < {min_correl})")
            return False, f"Face does not match your profile photo (similarity {similarity:.2f}). Use the same person as on your account, with clear lighting."
                
        except Exception as e:
            print(f"❌ [FACE] Verification runtime error: {e}")
            return False, f"Verification error: {str(e)}"