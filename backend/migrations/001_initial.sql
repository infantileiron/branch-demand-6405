--
-- PostgreSQL database dump
--

\restrict lXFB6fNpI4rXcksEIua5wCwsTi9dYlOU8AAtbpjjkZcdJKYCuoHM9Ug1Wwit1mc

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audits (
    id integer NOT NULL,
    actor character varying(100),
    action character varying(200),
    created character varying(40)
);


--
-- Name: audits_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audits_id_seq OWNED BY public.audits.id;


--
-- Name: daily_volumes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.daily_volumes (
    id integer NOT NULL,
    branch character varying(30) NOT NULL,
    day character varying(10) NOT NULL,
    volume integer NOT NULL,
    note text
);


--
-- Name: daily_volumes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.daily_volumes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_volumes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.daily_volumes_id_seq OWNED BY public.daily_volumes.id;


--
-- Name: forecast_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecast_runs (
    id integer NOT NULL,
    name character varying(100),
    branch character varying(30),
    backtest_days integer,
    alpha double precision,
    beta double precision,
    state character varying(20),
    result json,
    error text
);


--
-- Name: forecast_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.forecast_runs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: forecast_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.forecast_runs_id_seq OWNED BY public.forecast_runs.id;


--
-- Name: staffings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staffings (
    id integer NOT NULL,
    run_id integer,
    capacity integer,
    model character varying(30),
    schedule json,
    note text,
    status character varying(20)
);


--
-- Name: staffings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staffings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staffings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staffings_id_seq OWNED BY public.staffings.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying(100),
    password character varying(200),
    role character varying(20)
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: audits id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audits ALTER COLUMN id SET DEFAULT nextval('public.audits_id_seq'::regclass);


--
-- Name: daily_volumes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes ALTER COLUMN id SET DEFAULT nextval('public.daily_volumes_id_seq'::regclass);


--
-- Name: forecast_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_runs ALTER COLUMN id SET DEFAULT nextval('public.forecast_runs_id_seq'::regclass);


--
-- Name: staffings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings ALTER COLUMN id SET DEFAULT nextval('public.staffings_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: audits audits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audits
    ADD CONSTRAINT audits_pkey PRIMARY KEY (id);


--
-- Name: daily_volumes daily_volumes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes
    ADD CONSTRAINT daily_volumes_pkey PRIMARY KEY (id);


--
-- Name: forecast_runs forecast_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_runs
    ADD CONSTRAINT forecast_runs_pkey PRIMARY KEY (id);


--
-- Name: staffings staffings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings
    ADD CONSTRAINT staffings_pkey PRIMARY KEY (id);


--
-- Name: daily_volumes uq_branch_day; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.daily_volumes
    ADD CONSTRAINT uq_branch_day UNIQUE (branch, day);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: staffings staffings_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staffings
    ADD CONSTRAINT staffings_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.forecast_runs(id);


--


--
-- 区域协调（在初始快照之上追加）
--

CREATE TABLE public.regions (
    id integer NOT NULL,
    name character varying(60) NOT NULL,
    note text,
    created character varying(40)
);

CREATE SEQUENCE public.regions_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.regions_id_seq OWNED BY public.regions.id;
ALTER TABLE ONLY public.regions ALTER COLUMN id SET DEFAULT nextval('public.regions_id_seq'::regclass);
ALTER TABLE ONLY public.regions ADD CONSTRAINT regions_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.regions ADD CONSTRAINT regions_name_key UNIQUE (name);

CREATE TABLE public.region_members (
    id integer NOT NULL,
    region_id integer NOT NULL,
    branch character varying(30) NOT NULL
);

CREATE SEQUENCE public.region_members_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.region_members_id_seq OWNED BY public.region_members.id;
ALTER TABLE ONLY public.region_members ALTER COLUMN id SET DEFAULT nextval('public.region_members_id_seq'::regclass);
ALTER TABLE ONLY public.region_members ADD CONSTRAINT region_members_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.region_members ADD CONSTRAINT uq_region_branch UNIQUE (region_id, branch);
ALTER TABLE ONLY public.region_members ADD CONSTRAINT region_members_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

CREATE TABLE public.region_runs (
    id integer NOT NULL,
    region_id integer NOT NULL,
    region_name character varying(60),
    name character varying(100),
    week character varying(10) NOT NULL,
    version integer NOT NULL,
    backtest_days integer,
    alpha double precision,
    beta double precision,
    capacity integer,
    state character varying(20),
    result json,
    error text,
    request_key character varying(80),
    created character varying(40),
    published_at character varying(40),
    superseded_by integer
);

CREATE SEQUENCE public.region_runs_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.region_runs_id_seq OWNED BY public.region_runs.id;
ALTER TABLE ONLY public.region_runs ALTER COLUMN id SET DEFAULT nextval('public.region_runs_id_seq'::regclass);
ALTER TABLE ONLY public.region_runs ADD CONSTRAINT region_runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.region_runs ADD CONSTRAINT uq_region_week_version UNIQUE (region_id, week, version);
ALTER TABLE ONLY public.region_runs ADD CONSTRAINT uq_region_request_key UNIQUE (region_id, request_key);
ALTER TABLE ONLY public.region_runs ADD CONSTRAINT region_runs_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);

CREATE TABLE public.region_run_members (
    id integer NOT NULL,
    region_run_id integer NOT NULL,
    branch character varying(30) NOT NULL,
    state character varying(20),
    result json,
    error text
);

CREATE SEQUENCE public.region_run_members_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.region_run_members_id_seq OWNED BY public.region_run_members.id;
ALTER TABLE ONLY public.region_run_members ALTER COLUMN id SET DEFAULT nextval('public.region_run_members_id_seq'::regclass);
ALTER TABLE ONLY public.region_run_members ADD CONSTRAINT region_run_members_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.region_run_members ADD CONSTRAINT uq_region_run_branch UNIQUE (region_run_id, branch);
ALTER TABLE ONLY public.region_run_members ADD CONSTRAINT region_run_members_region_run_id_fkey FOREIGN KEY (region_run_id) REFERENCES public.region_runs(id);

ALTER TABLE public.staffings ADD COLUMN region_id integer;
ALTER TABLE public.staffings ADD COLUMN region_run_id integer;
ALTER TABLE public.staffings ADD COLUMN branch character varying(30);
ALTER TABLE public.staffings ADD COLUMN week character varying(10);
ALTER TABLE public.staffings ADD COLUMN basis json;
ALTER TABLE ONLY public.staffings ADD CONSTRAINT staffings_region_id_fkey FOREIGN KEY (region_id) REFERENCES public.regions(id);
ALTER TABLE ONLY public.staffings ADD CONSTRAINT staffings_region_run_id_fkey FOREIGN KEY (region_run_id) REFERENCES public.region_runs(id);

-- 区域每网点每周只保留一行排班；单点排班 region_id 为 NULL 时不受限
ALTER TABLE ONLY public.staffings ADD CONSTRAINT uq_region_week_branch UNIQUE (region_id, week, branch);

-- PostgreSQL database dump complete
--

\unrestrict lXFB6fNpI4rXcksEIua5wCwsTi9dYlOU8AAtbpjjkZcdJKYCuoHM9Ug1Wwit1mc

